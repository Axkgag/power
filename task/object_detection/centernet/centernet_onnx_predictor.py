#import pycuda.driver as cuda
import tensorrt as trt
import os
import time
import numpy as np
import torch
import cv2
import json
from PIL import Image, ImageDraw, ImageFont
from .lib.base_predictor import Predictor
from .lib.detectors.detector_factory import detector_factory
from .lib.opts import opts
from .lib.utils.image import get_affine_transform
from .lib import common
from .lib.models.decode import ctdet_decode
from .lib.utils.post_process import ctdet_post_process



def createInstance(config_path):
    predictor = CenterNetPredictor(config_path)
    return predictor

class CenterNetPredictor(Predictor):

    def __init__(self, config_path):
        super().__init__(config_path)
        opt = opts().parse()
        
        self.opt = opts().update_dataset_info_and_set_heads(opt, self.config)
        os.environ['CUDA_VISIBLE_DEVICES'] = self.opt.gpus_str
        self.model_path_=""
        self.class_names_=self.opt.class_names
        self.max_per_image = opt.K
        
        self.TRT_LOGGER = trt.Logger(trt.Logger.WARNING)

    # The Onnx path is used for Onnx models. export_path
    def build_engine_onnx(self, model_file):
        builder = trt.Builder(self.TRT_LOGGER)
        network = builder.create_network(common.EXPLICIT_BATCH)
        config = builder.create_builder_config()
        parser = trt.OnnxParser(network, self.TRT_LOGGER)

        config.max_workspace_size = common.GiB(1)
        # Load the Onnx model and parse it in order to populate the TensorRT network.
        with open(model_file, 'rb') as model:
            if not parser.parse(model.read()):
                print ('ERROR: Failed to parse the ONNX file.')
                for error in range(parser.num_errors):
                    print (parser.get_error(error))
                return None
        return builder.build_serialized_network(network, config)    

    
    def pre_process(self, image, pagelocked_buffer, scale, meta=None):
        height, width = image.shape[0:2]
        new_height = int(height * scale)
        new_width = int(width * scale)
        if self.opt.fix_res:
            inp_height, inp_width = self.opt.input_h, self.opt.input_w
            c = np.array([new_width / 2.0, new_height / 2.0], dtype=np.float32)
            s = max(height, width) * 1.0
        else:
            inp_height = (new_height | self.opt.pad) + 1
            inp_width = (new_width | self.opt.pad) + 1
            c = np.array([new_width // 2, new_height // 2], dtype=np.float32)
            s = np.array([inp_width, inp_height], dtype=np.float32)

        trans_input = get_affine_transform(c, s, 0, [inp_width, inp_height])
        resized_image = cv2.resize(image, (new_width, new_height))
        inp_image = cv2.warpAffine(
            resized_image, trans_input, (inp_width, inp_height), flags=cv2.INTER_LINEAR
        )
        inp_image = ((inp_image / 255.0 - self.opt.mean) / self.opt.std).astype(np.float32)

        images = inp_image.transpose(2, 0, 1).reshape(1, 3, inp_height, inp_width)
        
        meta = {
            "c": c,
            "s": s,
            "out_height": inp_height // self.opt.down_ratio,
            "out_width": inp_width // self.opt.down_ratio,
        }
        np.copyto(pagelocked_buffer, images.ravel())
        return images, meta
    
    def post_process(self, dets, meta, scale=1):
        dets = dets.detach().cpu().numpy()
        dets = dets.reshape(1, -1, dets.shape[2])
        dets = ctdet_post_process(
            dets.copy(), [meta['c']], [meta['s']],
            meta['out_height'], meta['out_width'], self.opt.num_classes)
        for j in range(1, self.opt.num_classes + 1):
            dets[0][j] = np.array(dets[0][j], dtype=np.float32).reshape(-1, 5)
            dets[0][j][:, :4] /= scale
        return dets[0]
    
    def merge_outputs(self, detections):
        results = {}
        for j in range(1, self.opt.num_classes + 1):
            results[j] = np.concatenate(
            [detection[j] for detection in detections], axis=0).astype(np.float32)
        scores = np.hstack([results[j][:, 4] for j in range(1, self.opt.num_classes + 1)])
        if len(scores) > self.max_per_image:
            kth = len(scores) - self.max_per_image
            thresh = np.partition(scores, kth)[kth]
            for j in range(1, self.opt.num_classes + 1):
                keep_inds = (results[j][:, 4] >= thresh)
                results[j] = results[j][keep_inds]
        return results

    def loadModel(self, model_dir_path):
        if len(model_dir_path)>0 and model_dir_path== self.model_path_:
            return True
        
        if not os.path.exists(model_dir_path):
            return False
        if not os.path.exists(os.path.join(model_dir_path,"model_best.pth")):
            return False
        if not os.path.exists(os.path.join(model_dir_path,"predictor.json")):
            return False
        with open(os.path.join(model_dir_path,"predictor.json"),'r', encoding='utf-8') as f:
            predictor_config=json.load(f)
            f.close()
        
        for key in predictor_config :
            self.config.set(key, predictor_config[key])
        if "score_threshold" in predictor_config:
            self.score_threshold=predictor_config["score_threshold"]
        print("score thres:",self.score_threshold)
        if not os.path.exists(os.path.join(self.opt.export_dir, "model.engine")):
            serialized_engine  = self.build_engine_onnx(os.path.join(model_dir_path, "model.onnx"))
            with open(os.path.join(model_dir_path, "model.engine"), "wb") as f:
                f.write(serialized_engine)
        else:
            print("found trt engine")
            with open(os.path.join(model_dir_path, "model.engine"), "rb") as f:
                serialized_engine = f.read()

        self.runtime = trt.Runtime(self.TRT_LOGGER)
        self.engine = self.runtime.deserialize_cuda_engine(serialized_engine)
        inputs, outputs, bindings, stream = common.allocate_buffers(self.engine)
        context = self.engine.create_execution_context()

        self.inputs = inputs
        self.outputs = outputs
        self.bindings = bindings
        self.stream = stream
        self.context = context

        self.model_path_=model_dir_path 
        return True

    def run_single(self, img_path):
        
        t0 = time.time()
        image = cv2.imread(img_path)
        detections = []
        scale = 1
        meta = None
        
        t1 = time.time()
        _, meta = self.pre_process(image, self.inputs[0].host, scale, meta)
        t2 = time.time()
        #ctx.push()
        trt_outputs = common.do_inference_v2(self.context, bindings=self.bindings, inputs=self.inputs, outputs=self.outputs, stream=self.stream)
        #ctx.pop()
        t3 = time.time()

        # print(type(trt_outputs))
        # print(type(trt_outputs[0]))
        hm = torch.from_numpy(np.array(trt_outputs[0]).reshape(1, self.opt.num_classes, 128, 128)).sigmoid_().cuda()
        wh = torch.from_numpy(np.array(trt_outputs[1]).reshape(1, 2, 128, 128)).cuda()
        reg = torch.from_numpy(np.array(trt_outputs[2]).reshape(1, 2, 128, 128)).cuda()
        
        t4 = time.time()
        
        dets = ctdet_decode(hm, wh, reg=reg, cat_spec_wh=self.opt.cat_spec_wh, K=self.opt.K)
        t5 = time.time()
        dets = self.post_process(dets, meta, scale)
        t6 = time.time()

        detections.append(dets)
        rets = self.merge_outputs(detections)
        t7 = time.time()
        print("img read time:", (t1-t0))
        print("pre-process time:", (t2-t1))
        print("forward time:", (t3-t2))
        print("toGPU time:", (t4-t3))
        print("decode time:", (t5-t4))
        print("post-process time:", (t6-t5))
        print("merge time:", (t7-t6))
        print("total time:", (t7-t0))
        return rets

    def predict(self, img_path):
        start_time = time.time()    
        result_dict = self.run_single(img_path)
        
        new_result_dict = {}
        ret = {}
        # 先阈值过滤
        for key in result_dict:
            for bbox_score in result_dict[key]:
                bbox=bbox_score[0:4]
                score=bbox_score[4]
                #print("key",key)
                if score <self.score_threshold[key-1]:
                    continue
                if key not in new_result_dict.keys():
                    new_result_dict[key] = []
                new_result_dict[key].append([bbox[0], bbox[1], bbox[2], bbox[3], score])
        
        # 再去除重复框
        results = self.filter_by_iou(new_result_dict)

        final_results={}

        for cat_id in results:
            cat_result=results[cat_id]
            filtered_cat_result=[]
            for bbox_score in cat_result:
                score=bbox_score[4]
                if score < self.score_threshold[cat_id-1] :
                    continue
                filtered_cat_result.append(bbox_score)
            final_results[self.class_names_[cat_id-1]]=filtered_cat_result
        ret["results"]=final_results
        end_time = time.time()
        print('time:', (end_time - start_time))
        return ret

    
    def stackPredict(self, img_path_list):
        pass
    
    def run_eval(self, img_dir, annotation_file, save_dir):
        import pycocotools.coco as coco
        from pycocotools.cocoeval import COCOeval
        coco_anno = coco.COCO(annotation_file)
        images = coco_anno.getImgIds()
        num_samples = len(images)
        class_name = ['__background__', ] + self.opt.class_names
        _valid_ids = [i for i in range(1, len(class_name)+1)]

        results = {}
        for index in range(num_samples):
            img_id = images[index]
            file_name = coco_anno.loadImgs(ids=[img_id])[0]['file_name']
            img_path = os.path.join(img_dir, file_name)
            results[img_id] = self.run_single(img_path)

        def _to_float(x):
            return float("{:.2f}".format(x))

        def convert_eval_format(all_bboxes):
            # import pdb; pdb.set_trace()
            detections = []
            for image_id in all_bboxes:
                for cls_ind in all_bboxes[image_id]:
                    category_id = _valid_ids[cls_ind - 1]
                    for bbox in all_bboxes[image_id][cls_ind]:
                        bbox[2] -= bbox[0]
                        bbox[3] -= bbox[1]
                        score = bbox[4]
                        bbox_out  = list(map(_to_float, bbox[0:4]))

                        detection = {
                            "image_id": int(image_id),
                            "category_id": int(category_id),
                            "bbox": bbox_out,
                            "score": float("{:.2f}".format(score))
                        }
                        if len(bbox) > 5:
                            extreme_points = list(map(_to_float, bbox[5:13]))
                            detection["extreme_points"] = extreme_points
                        detections.append(detection)
            return detections

        def save_results(results, save_dir):
            json.dump(convert_eval_format(results), 
                        open('{}/results.json'.format(save_dir), 'w'))
        
        save_results(results, save_dir)
        coco_dets = coco_anno.loadRes('{}/results.json'.format(save_dir))
        coco_eval = COCOeval(coco_anno, coco_dets, "bbox")
        coco_eval.evaluate()
        coco_eval.accumulate()
        coco_eval.summarize()

    def testFolder(self, folder_path):
        start_time = time.time()
        forward_time = 0
        if not os.path.exists(os.path.join(folder_path+"-results")):
            os.makedirs(os.path.join(folder_path+"-results"))
        if not hasattr(self,"color_list"):
            self.color_list=[]
            for i in range(256):
                self.color_list.append(tuple(((i*17)%256, (i+20)*67%256, (i+60)*101%256  )))
        
        data = []
        for root, dirs, files in os.walk(folder_path):
            for filename in files:
                data.append(os.path.join(root,filename))

        for ind, img_path in enumerate(data):
            img_name = os.path.basename(img_path)
            img = Image.open(img_path)
            
            t1 = time.time()
            result_dict = self.run_single(img_path)
            t2 = time.time()
            forward_time += (t2 - t1)

            # print(result_dict)
            new_result_dict = {}
            # 先阈值过滤
            for key in result_dict:
                for bbox_score in result_dict[key]:
                    bbox=bbox_score[0:4]
                    score=bbox_score[4]
                    #print("key",key)
                    if score <self.score_threshold[key-1]:
                        continue
                    if key not in new_result_dict.keys():
                        new_result_dict[key] = []
                    new_result_dict[key].append([bbox[0], bbox[1], bbox[2], bbox[3], score])
            
            # 再去除重复框
            new_result_dict = self.filter_by_iou(new_result_dict)
            color_index=0
            for key in new_result_dict:
                for bbox_score in new_result_dict[key]:
                    bbox = bbox_score[0:4]
                    score = bbox_score[4]
                    # if score < self.score_threshold[key-1]: continue
                    draw=ImageDraw.Draw(img)
                    if not hasattr(self,"font"):
                        self.font = ImageFont.truetype("./ttf/Alibaba-PuHuiTi-Regular.ttf", 10, encoding="utf-8"  )
                    draw.text( (int(bbox[0]),int(bbox[1])), self.class_names_[key-1],fill=self.color_list[color_index],font=self.font)
                    draw.text( (int(bbox[0]),int(bbox[1])-20), str(score),fill=self.color_list[color_index],font=self.font)
                    
                    draw.rectangle(tuple(bbox),outline=self.color_list[color_index],width=4)
                color_index+=1
            out_img_path=folder_path+"-results/"+str(img_name).split("/")[-1]
            # print("out imgname",out_img_path)
            img.save(out_img_path)
            
        end_time = time.time()
        print('avg time:', (end_time - start_time)/len(data) ," s" )
        print('forward time:', forward_time / len(data) ," s" )

        

    def modelPath(self):
        return self.model_path_

    def filter_by_iou(self, results):
        # results: 同一张图像中所有类别的boxes和scores: {cls_id: np.array([[x1, y1, x2, y2, score], [x1', y1', x2', y2', score'], ])}，经过阈值过滤后的预测结果
        def nms(dets, iou_thr):
            x1 = dets[:, 0]
            y1 = dets[:, 1]
            x2 = dets[:, 2]
            y2 = dets[:, 3]
            areas = (y2 -y1+1) * (x2 - x1+1)
            scores = dets[:, 4]
            keep = []
            index = areas.argsort()[::-1]
            while index.size > 0:
                i = index[0]
                keep.append(i)
                x11 = np.maximum(x1[i], x1[index[1:]])
                y11 = np.maximum(y1[i], y1[index[1:]])
                x22 = np.minimum(x2[i], x2[index[1:]])
                y22 = np.minimum(y2[i], y2[index[1:]])

                w = np.maximum(0, x22-x11+1)
                h = np.maximum(0, y22-y11+1)

                overlaps = w*h
                ious = overlaps / (areas[i]+areas[index[1:]] - overlaps)

                idx = np.where(ious <= iou_thr)[0]
                index = index[(idx+1)]
            return keep
        
        # 如果两个bboxes的iou大于0.5，则保留置信度较大的那个bbox
        new_results = {}
        bboxes = [] # annotation_id: bbox
        cls_ids = {} # annotation_id: cls_id
        anno = 0
        if len(results) == 0: return results
        for cls_id, bbox in results.items():
            bboxes.extend(list(bbox))
            new_results[cls_id] = []
            for _ in range(len(bbox)):
                cls_ids[anno] = cls_id
                anno += 1
        bboxes = np.stack(bboxes)
        keep_idx = nms(bboxes, self.opt.iou_thr)
        for idx in keep_idx:
            new_results[cls_ids[idx]].append(bboxes[idx])
        return new_results
            

    def cal_threshold(self, results_file, annotation_file):
        # 计算置信度阈值, IoU阈值设为0.3
        import pycocotools.coco as coco
        from pycocotools.cocoeval import COCOeval
        coco_anno = coco.COCO(annotation_file)
        images_ids = coco_anno.getImgIds()
        dets = coco_anno.loadRes(results_file)
        cat_ids = coco_anno.getCatIds()
        default_conf_thr = {cid:0.2 for cid in cat_ids}

        def iou(dets, gts, iou_thr):
            x1 = dets[:, 0]
            y1 = dets[:, 1]
            x2 = dets[:, 2]
            y2 = dets[:, 3]
            areas = (y2 -y1+1) * (x2 - x1+1)
            scores = dets[:, 4]
            min_score = 1.5 # 随便取的，只要比1.0大就行
            for i in range(len(gts)):
                bbox = gts[i][0:4]
                area = (bbox[3]-bbox[1]+1) * (bbox[2]-bbox[0]+1)
            
                x11 = np.maximum(bbox[0], x1)
                y11 = np.maximum(bbox[1], y1)
                x22 = np.minimum(bbox[2], x2)
                y22 = np.minimum(bbox[3], y2)

                w = np.maximum(0, x22-x11+1)
                h = np.maximum(0, y22-y11+1)

                overlaps = w*h
                ious = overlaps / (area+areas - overlaps)

                max_iou = np.max(ious)
                max_iou_idx = np.argmax(ious)
                if max_iou >= iou_thr:
                    best_score = scores[max_iou_idx]
                    if best_score < min_score:
                        min_score = best_score
            return min_score
        
        for cid in cat_ids:
            min_s = 1.5
            for iid in images_ids:
                gt_ann_ids = coco_anno.getAnnIds([iid], [cid])
                if len(gt_ann_ids) == 0: continue
                det_ann_ids = dets.getAnnIds([iid], [cid])
                if len(det_ann_ids) == 0: continue
                gt_anns = coco_anno.loadAnns(gt_ann_ids)
                det_anns = dets.loadAnns(det_ann_ids)
                gt_bboxes = []
                det_bboxes = []
                for ann in gt_anns:
                    bbox = ann['bbox']
                    gt_bboxes.append([bbox[0], bbox[1], bbox[0]+bbox[2], bbox[1]+bbox[3], 1.0])
                for ann in det_anns:
                    bbox = ann['bbox']
                    score = ann['score']
                    det_bboxes.append([bbox[0], bbox[1], bbox[0]+bbox[2], bbox[1]+bbox[3], score])
                gt_bboxes = np.array(gt_bboxes)
                det_bboxes = np.array(det_bboxes)
                
                min_score = iou(det_bboxes, gt_bboxes, iou_thr=0.5)
                if min_score < min_s:
                    min_s = min_score
            if min_s < default_conf_thr[cid]:
                default_conf_thr[cid] = min_s
        print(default_conf_thr)

        


    
