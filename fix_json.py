# fix_json.py
with open('config/characters.json', 'r', encoding='utf-8-sig') as f:
    content = f.read()  # Reads and skips BOM
with open('config/characters.json', 'w', encoding='utf-8') as f:
    f.write(content)  # Writes back without BOM
print("BOM removed, file rewritten.")