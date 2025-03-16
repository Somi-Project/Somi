import json
with open('config/characters.json', 'r') as f:
    raw_content = f.read()
    print(f'Raw content: "{raw_content}"')
    print(f'Length: {len(raw_content)}')
    f.seek(0)  # Rewind to start before parsing
    data = json.load(f)
    print(f'Parsed data: {data}')