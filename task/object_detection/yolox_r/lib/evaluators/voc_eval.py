#!/usr/bin/env python3
# Code are based on
# https://github.com/rbgirshick/py-faster-rcnn/blob/master/lib/datasets/voc_eval.py
# Copyright (c) Bharath Hariharan.
# Copyright (c) Megvii, Inc. and its affiliates.

import os
import pickle
import xml.etree.ElementTree as ET

import numpy as np
from dotadevkit.polyiou import polyiou


# def parse_rec(filename):
#     """Parse a PASCAL VOC xml file"""
#     tree = ET.parse(filename)
#     objects = []
#     for obj in tree.findall("object"):
#         obj_struct = {}
#         obj_struct["name"] = obj.find("name").text
#         obj_struct["pose"] = obj.find("pose").text
#         obj_struct["truncated"] = int(obj.find("truncated").text)
#         obj_struct["difficult"] = int(obj.find("difficult").text)
#         bbox = obj.find("bndbox")
#         obj_struct["bbox"] = [
#             int(bbox.find("xmin").text),
#             int(bbox.find("ymin").text),
#             int(bbox.find("xmax").text),
#             int(bbox.find("ymax").text),
#         ]
#         objects.append(obj_struct)
#
#     return objects
#
#
# def voc_ap(rec, prec, use_07_metric=False):
#     """
#     Compute VOC AP given precision and recall.
#     If use_07_metric is true, uses the
#     VOC 07 11 point method (default:False).
#     """
#     if use_07_metric:
#         # 11 point metric
#         ap = 0.0
#         for t in np.arange(0.0, 1.1, 0.1):
#             if np.sum(rec >= t) == 0:
#                 p = 0
#             else:
#                 p = np.max(prec[rec >= t])
#             ap = ap + p / 11.0
#     else:
#         # correct AP calculation
#         # first append sentinel values at the end
#         mrec = np.concatenate(([0.0], rec, [1.0]))
#         mpre = np.concatenate(([0.0], prec, [0.0]))
#
#         # compute the precision envelope
#         for i in range(mpre.size - 1, 0, -1):
#             mpre[i - 1] = np.maximum(mpre[i - 1], mpre[i])
#
#         # to calculate area under PR curve, look for points
#         # where X axis (recall) changes value
#         i = np.where(mrec[1:] != mrec[:-1])[0]
#
#         # and sum (\Delta recall) * prec
#         ap = np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1])
#     return ap
#
#
# def voc_eval(
#     detpath,
#     annopath,
#     imagesetfile,
#     classname,
#     cachedir,
#     ovthresh=0.5,
#     use_07_metric=False,
# ):
#     # first load gt
#     if not os.path.isdir(cachedir):
#         os.mkdir(cachedir)
#     cachefile = os.path.join(cachedir, "annots.pkl")
#     # read list of images
#     with open(imagesetfile, "r") as f:
#         lines = f.readlines()
#     imagenames = [x.strip() for x in lines]
#
#     if not os.path.isfile(cachefile):
#         # load annots
#         recs = {}
#         for i, imagename in enumerate(imagenames):
#             recs[imagename] = parse_rec(annopath.format(imagename))
#             if i % 100 == 0:
#                 print(f"Reading annotation for {i + 1}/{len(imagenames)}")
#         # save
#         print(f"Saving cached annotations to {cachefile}")
#         with open(cachefile, "wb") as f:
#             pickle.dump(recs, f)
#     else:
#         # load
#         with open(cachefile, "rb") as f:
#             recs = pickle.load(f)
#
#     # extract gt objects for this class
#     class_recs = {}
#     npos = 0
#     for imagename in imagenames:
#         R = [obj for obj in recs[imagename] if obj["name"] == classname]
#         bbox = np.array([x["bbox"] for x in R])
#         difficult = np.array([x["difficult"] for x in R]).astype(np.bool)
#         det = [False] * len(R)
#         npos = npos + sum(~difficult)
#         class_recs[imagename] = {"bbox": bbox, "difficult": difficult, "det": det}
#
#     # read dets
#     detfile = detpath.format(classname)
#     with open(detfile, "r") as f:
#         lines = f.readlines()
#
#     if len(lines) == 0:
#         return 0, 0, 0
#
#     splitlines = [x.strip().split(" ") for x in lines]
#     image_ids = [x[0] for x in splitlines]
#     confidence = np.array([float(x[1]) for x in splitlines])
#     BB = np.array([[float(z) for z in x[2:]] for x in splitlines])
#
#     # sort by confidence
#     sorted_ind = np.argsort(-confidence)
#     BB = BB[sorted_ind, :]
#     image_ids = [image_ids[x] for x in sorted_ind]
#
#     # go down dets and mark TPs and FPs
#     nd = len(image_ids)
#     tp = np.zeros(nd)
#     fp = np.zeros(nd)
#     for d in range(nd):
#         R = class_recs[image_ids[d]]
#         bb = BB[d, :].astype(float)
#         ovmax = -np.inf
#         BBGT = R["bbox"].astype(float)
#
#         if BBGT.size > 0:
#             # compute overlaps
#             # intersection
#             ixmin = np.maximum(BBGT[:, 0], bb[0])
#             iymin = np.maximum(BBGT[:, 1], bb[1])
#             ixmax = np.minimum(BBGT[:, 2], bb[2])
#             iymax = np.minimum(BBGT[:, 3], bb[3])
#             iw = np.maximum(ixmax - ixmin + 1.0, 0.0)
#             ih = np.maximum(iymax - iymin + 1.0, 0.0)
#             inters = iw * ih
#
#             # union
#             uni = (
#                 (bb[2] - bb[0] + 1.0) * (bb[3] - bb[1] + 1.0)
#                 + (BBGT[:, 2] - BBGT[:, 0] + 1.0) * (BBGT[:, 3] - BBGT[:, 1] + 1.0) - inters
#             )
#
#             overlaps = inters / uni
#             ovmax = np.max(overlaps)
#             jmax = np.argmax(overlaps)
#
#         if ovmax > ovthresh:
#             if not R["difficult"][jmax]:
#                 if not R["det"][jmax]:
#                     tp[d] = 1.0
#                     R["det"][jmax] = 1
#                 else:
#                     fp[d] = 1.0
#         else:
#             fp[d] = 1.0
#
#         # compute precision recall
#     fp = np.cumsum(fp)
#     tp = np.cumsum(tp)
#     rec = tp / float(npos)
#     # avoid divide by zero in case the first detection matches a difficult
#     # ground truth
#     prec = tp / np.maximum(tp + fp, np.finfo(np.float64).eps)
#     ap = voc_ap(rec, prec, use_07_metric)
#
#     return rec, prec, ap


def parse_gt(filename):
    """
    :param filename: ground truth file to parse
    :return: all instances in a picture
    """
    objects = []
    # filename = ./txt_gt/img_name.txt
    with open(filename, 'r') as f:
        while True:
            line = f.readline()
            if line:
                splitlines = line.strip().split(' ')
                object_struct = {}
                if len(splitlines) < 9:
                    continue
                object_struct['name'] = splitlines[8]

                if len(splitlines) == 9:
                    object_struct['difficult'] = 0
                elif len(splitlines) == 10:
                    object_struct['difficult'] = int(splitlines[9])
                object_struct['bbox'] = [float(splitlines[0]),
                                         float(splitlines[1]),
                                         float(splitlines[2]),
                                         float(splitlines[3]),
                                         float(splitlines[4]),
                                         float(splitlines[5]),
                                         float(splitlines[6]),
                                         float(splitlines[7])]
                objects.append(object_struct)
            else:
                break
    return objects

def voc_ap(rec, prec, use_07_metric=False):
    """ ap = voc_ap(rec, prec, [use_07_metric])
    Compute VOC AP given precision and recall.
    If use_07_metric is true, uses the
    VOC 07 11 point method (default:False).
    """
    if use_07_metric:
        # 11 point metric
        ap = 0.
        for t in np.arange(0., 1.1, 0.1):
            if np.sum(rec >= t) == 0:
                p = 0
            else:
                p = np.max(prec[rec >= t])
            ap = ap + p / 11.
    else:
        # correct AP calculation
        # first append sentinel values at the end
        mrec = np.concatenate(([0.], rec, [1.]))
        mpre = np.concatenate(([0.], prec, [0.]))

        # compute the precision envelope
        for i in range(mpre.size - 1, 0, -1):
            mpre[i - 1] = np.maximum(mpre[i - 1], mpre[i])

        # to calculate area under PR curve, look for points
        # where X axis (recall) changes value
        i = np.where(mrec[1:] != mrec[:-1])[0]

        # and sum (\Delta recall) * prec
        ap = np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1])
    return ap


def voc_eval(detpath,   # txt_predict/class_name.txt
             annopath,  # txt_gt/img_name.txt
             imagesetfile,  # valset.txt
             classname,
             ovthresh=0.5,
             use_07_metric=False):
    """rec, prec, ap = voc_eval(detpath,
                                annopath,
                                imagesetfile,
                                classname,
                                [ovthresh],
                                [use_07_metric])
    Top level function that does the PASCAL VOC evaluation.
    detpath: Path to detections
        detpath.format(classname) should produce the detection results file.
    annopath: Path to annotations
        annopath.format(imagename) should be the xml annotations file.
    imagesetfile: Text file containing the list of images, one image per line.
    classname: Category name (duh)
    cachedir: Directory for caching the annotations
    [ovthresh]: Overlap threshold (default = 0.5)
    [use_07_metric]: Whether to use VOC07's 11 point AP computation
        (default False)
    """

    # read list of images
    with open(imagesetfile, 'r') as f:
        lines = f.readlines()
    imagenames = [x.strip() for x in lines]

    recs = {}
    for i, imagename in enumerate(imagenames):
        recs[imagename] = parse_gt(annopath.format(imagename))
        # annopath.format(imagename) = ./txt_gt/img_name.txt

    # extract gt objects for this class
    class_recs = {}
    npos = 0
    for imagename in imagenames:
        R = [obj for obj in recs[imagename] if obj['name'] == classname]
        bbox = np.array([x['bbox'] for x in R])
        difficult = np.array([x['difficult'] for x in R]).astype(np.bool)
        det = [False] * len(R)
        npos = npos + sum(~difficult)
        class_recs[imagename] = {'bbox': bbox,
                                 'difficult': difficult,
                                 'det': det}

    # read dets from Task1* files
    detfile = detpath.format(classname)
    with open(detfile, 'r') as f:
        lines = f.readlines()

    splitlines = [x.strip().split(' ') for x in lines]
    image_ids = [x[0] for x in splitlines]
    confidence = np.array([float(x[1]) for x in splitlines])

    BB = np.array([[float(z) for z in x[2:]] for x in splitlines])

    if(len(BB)==0): return 0, 0, 0

    # sort by confidence
    sorted_ind = np.argsort(-confidence)
    sorted_scores = np.sort(-confidence)

    ## note the usage only in numpy not for list
    BB = BB[sorted_ind, :]
    image_ids = [image_ids[x] for x in sorted_ind]

    # go down dets and mark TPs and FPs
    nd = len(image_ids)
    tp = np.zeros(nd)
    fp = np.zeros(nd)
    for d in range(nd):
        R = class_recs[image_ids[d]]
        bb = BB[d, :].astype(float)
        ovmax = -np.inf
        BBGT = R['bbox'].astype(float)

        ## compute det bb with each BBGT

        if BBGT.size > 0:
            # compute overlaps
            # intersection

            # 1. calculate the overlaps between hbbs, if the iou between hbbs are 0, the iou between obbs are 0, too.
            # pdb.set_trace()
            BBGT_xmin =  np.min(BBGT[:, 0::2], axis=1)
            BBGT_ymin = np.min(BBGT[:, 1::2], axis=1)
            BBGT_xmax = np.max(BBGT[:, 0::2], axis=1)
            BBGT_ymax = np.max(BBGT[:, 1::2], axis=1)
            bb_xmin = np.min(bb[0::2])
            bb_ymin = np.min(bb[1::2])
            bb_xmax = np.max(bb[0::2])
            bb_ymax = np.max(bb[1::2])

            ixmin = np.maximum(BBGT_xmin, bb_xmin)
            iymin = np.maximum(BBGT_ymin, bb_ymin)
            ixmax = np.minimum(BBGT_xmax, bb_xmax)
            iymax = np.minimum(BBGT_ymax, bb_ymax)
            iw = np.maximum(ixmax - ixmin + 1., 0.)
            ih = np.maximum(iymax - iymin + 1., 0.)
            inters = iw * ih

            # union
            uni = ((bb_xmax - bb_xmin + 1.) * (bb_ymax - bb_ymin + 1.) +
                   (BBGT_xmax - BBGT_xmin + 1.) *
                   (BBGT_ymax - BBGT_ymin + 1.) - inters)

            overlaps = inters / uni

            BBGT_keep_mask = overlaps > 0
            BBGT_keep = BBGT[BBGT_keep_mask, :]
            BBGT_keep_index = np.where(overlaps > 0)[0]
            # pdb.set_trace()
            def calcoverlaps(BBGT_keep, bb):
                overlaps = []
                for index, GT in enumerate(BBGT_keep):

                    overlap = polyiou.iou_poly(polyiou.VectorDouble(BBGT_keep[index]), polyiou.VectorDouble(bb))
                    overlaps.append(overlap)
                return overlaps
            if len(BBGT_keep) > 0:
                overlaps = calcoverlaps(BBGT_keep, bb)

                ovmax = np.max(overlaps)
                jmax = np.argmax(overlaps)
                # pdb.set_trace()
                jmax = BBGT_keep_index[jmax]

        if ovmax > ovthresh:
            if not R['difficult'][jmax]:
                if not R['det'][jmax]:
                    tp[d] = 1.
                    R['det'][jmax] = 1
                else:
                    fp[d] = 1.
        else:
            fp[d] = 1.

    # compute precision recall

    # print('check fp:', fp)
    # print('check tp', tp)
    #
    #
    # print('npos num:', npos)
    fp = np.cumsum(fp)
    tp = np.cumsum(tp)

    rec = tp / float(npos)
    # avoid divide by zero in case the first detection matches a difficult
    # ground truth
    prec = tp / np.maximum(tp + fp, np.finfo(np.float64).eps)
    ap = voc_ap(rec, prec, use_07_metric)

    return rec, prec, ap