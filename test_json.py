import json
with open('config/characters.json', 'r') as f:
    data = json.load(f)
    print(data)