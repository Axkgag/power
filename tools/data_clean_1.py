import os
import xml.etree.ElementTree as ET
import shutil

def get_catlist(txt_path):
    with open(txt_path) as lf:
        cat_lines = lf.readlines()
        lf.close()
    cat_list = []
    for cat_name in cat_lines:
        cat_code = cat_name.split(' ')[1]
        cat_list.append(cat_code[:-1])
    # cat_dict1 = {}
    # cat_dict = {}
    # for id, cat_line in enumerate(cat_lines):
    #     # cat_dict1[id] = cat_line[:-1]
    #     cat_dict[cat_line[:-1]] = id + 1
    return cat_list

def get_xml(data_path, cat_dict):
    old_xml_path = os.path.join(data_path, "xml")
    old_img_path = os.path.join(data_path, "image")
    xml_list = os.listdir(old_xml_path)
    xml_list.sort()
    new_img_path = os.path.join(data_path, "del_image")
    if not os.path.exists(new_img_path):
        os.mkdir(new_img_path)
    new_xml_path = os.path.join(data_path, "del_xml")
    if not os.path.exists(new_xml_path):
        os.mkdir(new_xml_path)
    for xml_name in xml_list:
        tree = ET.parse(os.path.join(old_xml_path, xml_name))
        objs = tree.findall("object")
        img_name = tree.find("filename").text
        flag = 0
        for obj in objs:
            cat_name = obj.find("code").text
            if cat_name in cat_dict:
                flag = 1
                break
        if flag == 1:
            continue
        else:
            old_img = os.path.join(old_img_path, img_name)
            old_xml = os.path.join(old_xml_path, xml_name)
            new_img = os.path.join(new_img_path, img_name)
            new_xml = os.path.join(new_xml_path, xml_name)
            shutil.move(old_xml, new_xml)
            shutil.move(old_img, new_img)


if __name__ == "__main__":
    data_path = "/data/gauss/lyh/datasets/power_networks/train/"
    txt_path = os.path.join(data_path, "class_name.txt")
    cat_list = get_catlist(txt_path)
    get_xml(data_path, cat_list)
