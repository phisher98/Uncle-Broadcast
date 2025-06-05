import xml.etree.ElementTree as ET
import shutil
import os

def prefix_epg_ids(input_file, output_file, prefix):
    tree = ET.parse(input_file)
    root = tree.getroot()
    # Update channel ids
    for channel in root.findall('channel'):
        channel_id = channel.get('id')
        if channel_id:
            channel.set('id', f"{prefix}.{channel_id}")
    # Update programme channel refs
    for programme in root.findall('programme'):
        prog_channel = programme.get('channel')
        if prog_channel:
            programme.set('channel', f"{prefix}.{prog_channel}")
    tree.write(output_file, encoding='utf-8', xml_declaration=True)

def merge_epg_files(xml_files, output_file):
    # Parse the first file (will be the base)
    base_tree = ET.parse(xml_files[0])
    base_root = base_tree.getroot()

    # Add channels and programmes from the rest
    for file in xml_files[1:]:
        tree = ET.parse(file)
        root = tree.getroot()
        for channel in root.findall('channel'):
            base_root.append(channel)
        for programme in root.findall('programme'):
            base_root.append(programme)

    base_tree.write(output_file, encoding='utf-8', xml_declaration=True)

if __name__ == "__main__":
    input_xml = "daddylive-channels-epg.xml"
    b_files = []
    for b in range(1, 4):
        prefix = f"z{b}"
        output_xml = f"daddylive-channels-epg_{prefix}.xml"
        prefix_epg_ids(input_xml, output_xml, prefix)
        b_files.append(output_xml)
    print("Created:", ", ".join(b_files))

    # Merge files: original + all b*
    all_files = [input_xml] + b_files
    merge_epg_files(all_files, "guide.xml")
    print("Merged into guide.xml")
