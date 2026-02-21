import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QLineEdit, QPushButton, QComboBox, QMessageBox, QInputDialog
)
from PyQt6.QtCore import Qt
import json
import os
import copy
import logging
from ollama import Client
from gui.themes import app_stylesheet

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class PersonaEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Somi Personality Editor")
        self.resize(900, 700)
        self.setStyleSheet(app_stylesheet())

        self.ollama = Client(host='http://localhost:11434')
        self.fields = ["role", "temperature", "description", "physicality", "experience", "inhibitions", "hobbies", "behaviors"]
        self.text_areas = {}
        self.current_personality = {}
        self.current_persona_name = None
        self.personality_backup = None

        # Main widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Persona selection
        persona_layout = QHBoxLayout()
        main_layout.addLayout(persona_layout)
        persona_label = QLabel("Select Persona:")
        persona_layout.addWidget(persona_label)
        self.persona_var = QComboBox()
        self.persona_var.setEditable(False)
        self.persona_var.currentTextChanged.connect(self.load_selected_persona)
        persona_layout.addWidget(self.persona_var)

        # Buttons
        button_layout = QVBoxLayout()
        main_layout.addLayout(button_layout)
        buttons = [
            ("Load personalC.json", self.load_personality),
            ("Add/Edit Persona", self.add_or_edit_persona),
            ("Remove Persona", self.remove_persona),
            ("Undo Last Action", self.undo_action),
            ("Save Personality", self.save_personality),
        ]
        for text, command in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(command)
            button_layout.addWidget(btn)

        # Text areas for fields
        for field in self.fields:
            field_layout = QHBoxLayout()
            main_layout.addLayout(field_layout)
            label = QLabel(field.capitalize())
            label.setFixedWidth(100)
            field_layout.addWidget(label)
            if field in ["role", "temperature", "description"]:
                text_area = QLineEdit()
            else:
                text_area = QTextEdit()
                text_area.setFixedHeight(60)
            field_layout.addWidget(text_area)
            self.text_areas[field] = text_area

        # Output area
        main_layout.addWidget(QLabel("Generated Personality Preview"))
        self.output_area = QTextEdit()
        self.output_area.setFixedHeight(200)
        self.output_area.setReadOnly(True)
        main_layout.addWidget(self.output_area)

    def load_personality(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(base_dir, "config", "personalC.json")
            if not os.path.exists(file_path):
                QMessageBox.critical(self, "Error", f"Configuration file not found at {file_path}")
                return
            with open(file_path, 'r') as f:
                self.current_personality = json.load(f)
            logging.debug(f"Loaded personality: {list(self.current_personality.keys())}")

            # Update persona dropdown
            persona_names = [key for key in self.current_personality.keys() if key.startswith("Name: ")]
            self.persona_var.clear()
            self.persona_var.addItems(persona_names)
            if persona_names:
                self.persona_var.setCurrentText(persona_names[0])
                self.load_selected_persona(persona_names[0])
            else:
                self.persona_var.setCurrentText("")
                self.clear_gui()

            QMessageBox.information(self, "Success", "Personality loaded successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load personality: {e}")

    def load_selected_persona(self, persona_name):
        try:
            self.current_persona_name = persona_name
            if not self.current_persona_name:
                self.clear_gui()
                return

            persona_data = self.current_personality.get(self.current_persona_name, {})
            for field in self.fields:
                if isinstance(self.text_areas[field], QTextEdit):
                    self.text_areas[field].clear()
                    value = persona_data.get(field, "")
                    if isinstance(value, list):
                        self.text_areas[field].setPlainText("\n".join(value))
                    else:
                        self.text_areas[field].setPlainText(str(value))
                else:
                    self.text_areas[field].setText(str(persona_data.get(field, "")))

            # Update preview
            self.output_area.setPlainText(json.dumps({self.current_persona_name: persona_data}, indent=4))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load persona: {e}")

    def clear_gui(self):
        for field in self.fields:
            if isinstance(self.text_areas[field], QTextEdit):
                self.text_areas[field].clear()
            else:
                self.text_areas[field].setText("")
        self.output_area.clear()
        self.current_persona_name = None

    def add_or_edit_persona(self):
        reply = QMessageBox.question(
            self, "Add or Edit", "Do you want to add a new persona? Click 'Yes' to add, 'No' to edit an existing one.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.add_new_persona()
        else:
            self.edit_existing_persona()

    def add_new_persona(self):
        persona_name, ok = QInputDialog.getText(self, "Persona Name", "Enter the name for the new persona (e.g., 'Somi', 'Alex'):")
        if not ok or not persona_name.strip():
            QMessageBox.critical(self, "Error", "Persona name cannot be empty.")
            return
        persona_name = persona_name.strip()
        persona_key = f"Name: {persona_name}"
        if persona_key in self.current_personality:
            QMessageBox.critical(self, "Error", f"Persona '{persona_name}' already exists. Choose a different name.")
            return

        prompt_input, ok = QInputDialog.getText(self, "New Personality Prompt", "Describe the new personality (e.g., 'F1 racecar driver'):")
        if not ok or not prompt_input:
            return

        try:
            self.output_area.setPlainText("Generating new personality, please wait...")

            # Load template
            base_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(base_dir, "config", "personalC.json")
            with open(file_path, 'r') as f:
                template_personality = json.load(f)
            template_persona = template_personality.get("Name: Somi", {})

            # Create prompt
            prompt = f"""
You are a personality editor for an AI assistant. Your task is to create a new personality configuration based on the user’s input, using the provided template structure. The template is provided below in JSON format to show the expected structure. You must output a JSON object containing ONLY the new personality with the key "Name: {persona_name}", in the EXACT same structure as the template. Do NOT include other personas, do NOT modify existing personas, and do NOT include additional text, comments, or deviations from the structure. Ensure each list (physicality, experience, inhibitions, hobbies, behaviors) contains EXACTLY 12 items, with behaviors containing 12 single-word traits.

Template Structure:
{json.dumps({"Name: Somi": template_persona}, indent=4)}

User Input for New Personality:
"{prompt_input}"

Create a new personality for the AI as a {prompt_input}. Set the 'role' to a suitable role for a {prompt_input} and 'temperature' to an appropriate value between 0.5 and 1.0. Fill each list with traits and actions relevant to a {prompt_input}. Output ONLY the new personality configuration in JSON format:
{{
    "Name: {persona_name}": {{...}}
}}
"""
            logging.debug(f"Sending prompt to Ollama for new persona: {prompt_input}")
            response = self.ollama.generate(model="codegemma", prompt=prompt)
            raw_output = response["response"].strip()
            logging.debug(f"Received raw response from Ollama: {raw_output}")

            # Strip Markdown code block markers
            if raw_output.startswith("```json"):
                raw_output = raw_output[len("```json"):].strip()
            if raw_output.endswith("```"):
                raw_output = raw_output[:-len("```")].strip()

            # Validate and parse JSON
            if not raw_output:
                raise ValueError("Empty response from Ollama")
            try:
                new_personality = json.loads(raw_output)
            except json.JSONDecodeError as je:
                logging.error(f"Invalid JSON response from Ollama: {raw_output}")
                raise ValueError(f"Failed to parse Ollama response as JSON: {je}")

            # Validate response structure
            if not isinstance(new_personality, dict) or persona_key not in new_personality:
                raise ValueError(f"Ollama response must contain only the key '{persona_key}', got: {list(new_personality.keys())}")
            if len(new_personality) != 1:
                raise ValueError(f"Ollama response must contain exactly one persona, got: {list(new_personality.keys())}")

            # Validate list lengths
            persona_data = new_personality[persona_key]
            for field in ["physicality", "experience", "inhibitions", "hobbies", "behaviors"]:
                if field in persona_data and len(persona_data[field]) != 12:
                    raise ValueError(f"Field '{field}' must contain exactly 12 items, got {len(persona_data[field])}")

            # Backup personality
            logging.debug(f"Before adding persona, current_personality keys: {list(self.current_personality.keys())}")
            self.personality_backup = copy.deepcopy(self.current_personality)

            # Add new persona
            self.current_personality[persona_key] = persona_data
            logging.debug(f"After adding persona, current_personality keys: {list(self.current_personality.keys())}")

            # Update dropdown
            self.persona_var.clear()
            self.persona_var.addItems(list(self.current_personality.keys()))
            self.persona_var.setCurrentText(persona_key)

            # Update GUI
            self.output_area.setPlainText(json.dumps({persona_key: persona_data}, indent=4))
            for field in self.fields:
                if isinstance(self.text_areas[field], QTextEdit):
                    self.text_areas[field].clear()
                    value = persona_data.get(field, "")
                    if isinstance(value, list):
                        self.text_areas[field].setPlainText("\n".join(value))
                    else:
                        self.text_areas[field].setPlainText(str(value))
                else:
                    self.text_areas[field].setText(str(persona_data.get(field, "")))

            QMessageBox.information(self, "Success", f"New personality '{persona_name}' added! Click 'Undo' to revert.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add new personality: {e}")

    def edit_existing_persona(self):
        if not self.current_persona_name:
            QMessageBox.critical(self, "Error", "Please select a persona to edit.")
            return

        fields_text, ok = QInputDialog.getText(
            self, "Fields to Edit", f"Enter the fields to edit (comma-separated, e.g., 'description,physicality'), choose from: {', '.join(self.fields)}:"
        )
        if not ok or not fields_text:
            return
        fields_to_edit = [f.strip() for f in fields_text.split(",") if f.strip() in self.fields]
        if not fields_to_edit:
            QMessageBox.critical(self, "Error", "No valid fields selected.")
            return

        prompt_input, ok = QInputDialog.getText(
            self, "Edit Prompt", f"Describe the changes for the fields {', '.join(fields_to_edit)} (e.g., 'Make description more adventurous, update physicality to reflect a mechanic'):"
        )
        if not ok or not prompt_input:
            return

        try:
            persona_data = self.current_personality[self.current_persona_name]
            prompt = f"""
You are a personality editor for an AI assistant. Your task is to edit specific fields of an existing personality configuration based on the user’s input. The existing personality is provided below in JSON format. You must output the updated personality in the EXACT same JSON structure, editing ONLY the specified fields to reflect the user’s input. Do NOT add extra text, comments, or deviate from the structure. For list fields, ensure EXACTLY 12 items, with behaviors containing 12 single-word traits.

Existing Personality:
{json.dumps({self.current_persona_name: persona_data}, indent=4)}

Fields to Edit:
{', '.join(fields_to_edit)}

User Input for Changes:
"{prompt_input}"

Update the specified fields ({', '.join(fields_to_edit)}) as described in the user input. Ensure the JSON structure remains identical, only modifying the content of the listed fields. Output the updated personality configuration in JSON format with the key "{self.current_persona_name}".
"""
            logging.debug(f"Sending prompt to Ollama for editing persona: {self.current_persona_name}")
            response = self.ollama.generate(model="codegemma", prompt=prompt)
            raw_output = response["response"].strip()
            logging.debug(f"Received raw response from Ollama: {raw_output}")

            # Strip Markdown code block markers
            if raw_output.startswith("```json"):
                raw_output = raw_output[len("```json"):].strip()
            if raw_output.endswith("```"):
                raw_output = raw_output[:-len("```")].strip()

            # Validate and parse JSON
            if not raw_output:
                raise ValueError("Empty response from Ollama")
            try:
                updated_personality = json.loads(raw_output)
            except json.JSONDecodeError as je:
                logging.error(f"Invalid JSON response from Ollama: {raw_output}")
                raise ValueError(f"Failed to parse Ollama response as JSON: {je}")

            # Validate response structure
            if not isinstance(updated_personality, dict) or self.current_persona_name not in updated_personality:
                raise ValueError(f"Ollama response must contain only the key '{self.current_persona_name}', got: {list(updated_personality.keys())}")
            if len(updated_personality) != 1:
                raise ValueError(f"Ollama response must contain exactly one persona, got: {list(updated_personality.keys())}")

            # Backup personality
            logging.debug(f"Before editing persona, current_personality keys: {list(self.current_personality.keys())}")
            self.personality_backup = copy.deepcopy(self.current_personality)

            # Update persona
            self.current_personality[self.current_persona_name] = updated_personality[self.current_persona_name]
            logging.debug(f"After editing persona, current_personality keys: {list(self.current_personality.keys())}")

            # Update GUI
            self.output_area.setPlainText(json.dumps({self.current_persona_name: updated_personality[self.current_persona_name]}, indent=4))
            for field in self.fields:
                if isinstance(self.text_areas[field], QTextEdit):
                    self.text_areas[field].clear()
                    value = updated_personality[self.current_persona_name].get(field, "")
                    if isinstance(value, list):
                        self.text_areas[field].setPlainText("\n".join(value))
                    else:
                        self.text_areas[field].setPlainText(str(value))
                else:
                    self.text_areas[field].setText(str(updated_personality[self.current_persona_name].get(field, "")))

            QMessageBox.information(self, "Success", f"Persona '{self.current_persona_name}' updated successfully! Click 'Undo' to revert.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to edit personality: {e}")

    def remove_persona(self):
        if not self.current_persona_name:
            QMessageBox.critical(self, "Error", "Please select a persona to remove.")
            return

        reply = QMessageBox.question(
            self, "Confirm Removal", f"Are you sure you want to remove the persona '{self.current_persona_name}'? Changes will be permanent after saving.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if self.current_persona_name not in self.current_personality:
                raise ValueError(f"Persona '{self.current_persona_name}' does not exist.")

            logging.debug(f"Before removing persona, current_personality keys: {list(self.current_personality.keys())}")
            self.personality_backup = copy.deepcopy(self.current_personality)

            del self.current_personality[self.current_persona_name]
            logging.debug(f"After removing persona, current_personality keys: {list(self.current_personality.keys())}")

            persona_names = [key for key in self.current_personality.keys() if key.startswith("Name: ")]
            self.persona_var.clear()
            self.persona_var.addItems(persona_names)
            if persona_names:
                self.persona_var.setCurrentText(persona_names[0])
                self.load_selected_persona(persona_names[0])
            else:
                self.persona_var.setCurrentText("")
                self.clear_gui()

            QMessageBox.information(self, "Success", f"Persona '{self.current_persona_name}' removed! Click 'Undo' to restore.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove persona: {e}")

    def undo_action(self):
        if not self.personality_backup:
            QMessageBox.information(self, "Info", "No action to undo.")
            return

        try:
            logging.debug(f"Undoing action, restoring personality keys: {list(self.personality_backup.keys())}")
            self.current_personality = copy.deepcopy(self.personality_backup)
            self.personality_backup = None
            persona_names = [key for key in self.current_personality.keys() if key.startswith("Name: ")]
            self.persona_var.clear()
            self.persona_var.addItems(persona_names)
            if persona_names:
                self.persona_var.setCurrentText(persona_names[0])
                self.load_selected_persona(persona_names[0])
            else:
                self.persona_var.setCurrentText("")
                self.clear_gui()
            QMessageBox.information(self, "Success", "Last action undone.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to undo action: {e}")

    def save_personality(self):
        try:
            if self.current_persona_name:
                persona_data = {}
                for field in self.fields:
                    if isinstance(self.text_areas[field], QTextEdit):
                        value = self.text_areas[field].toPlainText().strip()
                    else:
                        value = self.text_areas[field].text().strip()
                    if field in ["physicality", "experience", "inhibitions", "hobbies", "behaviors"]:
                        persona_data[field] = [line for line in value.split("\n") if line.strip()]
                    elif field == "temperature":
                        try:
                            persona_data[field] = float(value) if value.strip() else 0.7
                            if not 0.0 <= persona_data[field] <= 1.0:
                                raise ValueError("Temperature must be between 0.0 and 1.0")
                        except ValueError as ve:
                            QMessageBox.critical(self, "Error", f"Invalid temperature value: {value}. Must be a number between 0.0 and 1.0")
                            return
                    else:
                        persona_data[field] = value
                self.current_personality[self.current_persona_name] = persona_data

            base_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(base_dir, "config", "personalC.json")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            logging.debug(f"Saving personality with keys: {list(self.current_personality.keys())}")
            with open(file_path, 'w') as f:
                json.dump(self.current_personality, f, indent=4)

            self.personality_backup = None
            QMessageBox.information(self, "Success", f"Personality saved to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save personality: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PersonaEditor()
    window.show()
    sys.exit(app.exec())