import json

def load_character_config(character_name, file_path="config/personalC.json"):
    with open(file_path, 'r') as f:
        characters = json.load(f)
    if character_name not in characters:
        raise ValueError(f"Character '{character_name}' not found in {file_path}")
    return characters[character_name]