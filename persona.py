import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import json
import os
from ollama import Client

class PersonaEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Somi Personality Editor")
        self.root.geometry("900x700")

        self.ollama = Client(host='http://localhost:11434')
        self.fields = ["role", "temperature", "description", "physicality", "experience", "inhibitions", "hobbies", "behaviors"]
        self.text_areas = {}
        self.current_personality = {}
        self.current_persona_name = None
        self.personality_backup = None  # Store backup for undo

        # Persona selection
        self.persona_frame = tk.Frame(root)
        self.persona_frame.pack(pady=5)
        tk.Label(self.persona_frame, text="Select Persona:").pack(side=tk.LEFT)
        self.persona_var = tk.StringVar()
        self.persona_dropdown = ttk.Combobox(self.persona_frame, textvariable=self.persona_var, state="readonly")
        self.persona_dropdown.bind("<<ComboboxSelected>>", self.load_selected_persona)
        self.persona_dropdown.pack(side=tk.LEFT, padx=5)

        # Buttons
        tk.Button(root, text="Load personalC.json", command=self.load_personality).pack(pady=5)
        tk.Button(root, text="Add/Edit Persona", command=self.add_or_edit_persona).pack(pady=5)
        tk.Button(root, text="Remove Persona", command=self.remove_persona).pack(pady=5)
        tk.Button(root, text="Undo Last Action", command=self.undo_action).pack(pady=5)
        tk.Button(root, text="Save Personality", command=self.save_personality).pack(pady=5)

        # Text areas for fields
        for field in self.fields:
            frame = tk.Frame(root)
            frame.pack(pady=3, fill=tk.BOTH)
            tk.Label(frame, text=field.capitalize(), width=12, anchor="w").pack(side=tk.LEFT)
            if field in ["role", "description", "temperature"]:
                text_area = tk.Text(frame, height=1, width=80)
            else:
                text_area = tk.Text(frame, height=3, width=80)
            text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.text_areas[field] = text_area

        tk.Label(root, text="Generated Personality Preview").pack(pady=5)
        self.output_area = tk.Text(root, height=12, width=100)
        self.output_area.pack(pady=5)

    def load_personality(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(base_dir, "config", "personalC.json")
            if not os.path.exists(file_path):
                messagebox.showerror("Error", f"Configuration file not found at {file_path}")
                return
            with open(file_path, 'r') as f:
                self.current_personality = json.load(f)

            # Update persona dropdown
            persona_names = [key for key in self.current_personality.keys() if key.startswith("Name: ")]
            self.persona_dropdown["values"] = persona_names
            if persona_names:
                self.persona_var.set(persona_names[0])
                self.load_selected_persona(None)
            else:
                self.persona_var.set("")
                self.clear_gui()

            messagebox.showinfo("Success", "Personality loaded successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load personality: {e}")

    def load_selected_persona(self, event):
        try:
            self.current_persona_name = self.persona_var.get()
            if not self.current_persona_name:
                self.clear_gui()
                return

            persona_data = self.current_personality.get(self.current_persona_name, {})
            for field in self.fields:
                self.text_areas[field].delete(1.0, tk.END)
                value = persona_data.get(field, "")
                if isinstance(value, list):
                    self.text_areas[field].insert(tk.END, "\n".join(value))
                else:
                    self.text_areas[field].insert(tk.END, str(value))

            # Update preview
            self.output_area.delete(1.0, tk.END)
            self.output_area.insert(tk.END, json.dumps({self.current_persona_name: persona_data}, indent=4))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load persona: {e}")

    def clear_gui(self):
        """Clear all text areas and the preview area."""
        for field in self.fields:
            self.text_areas[field].delete(1.0, tk.END)
        self.output_area.delete(1.0, tk.END)
        self.current_persona_name = None

    def add_or_edit_persona(self):
        # Ask user to add new or edit existing
        action = messagebox.askquestion("Add or Edit", "Do you want to add a new persona? Click 'Yes' to add, 'No' to edit an existing one.")
        
        if action == "yes":
            self.add_new_persona()
        else:
            self.edit_existing_persona()

    def add_new_persona(self):
        persona_name = simpledialog.askstring("Persona Name", "Enter the name for the new persona (e.g., 'Somi', 'Alex'):")
        if not persona_name or not persona_name.strip():
            messagebox.showerror("Error", "Persona name cannot be empty.")
            return
        persona_name = persona_name.strip()
        persona_key = f"Name: {persona_name}"
        if persona_key in self.current_personality:
            messagebox.showerror("Error", f"Persona '{persona_name}' already exists. Choose a different name.")
            return

        prompt_input = simpledialog.askstring("New Personality Prompt", "Describe the new personality (e.g., 'F1 racecar driver'):")
        if not prompt_input:
            return

        try:
            # Show processing message
            self.output_area.delete(1.0, tk.END)
            self.output_area.insert(tk.END, "Generating new personality, please wait...")
            self.root.update()

            # Load the template (use Somi as the structure example)
            base_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(base_dir, "config", "personalC.json")
            with open(file_path, 'r') as f:
                template_personality = json.load(f)
            template_persona = template_personality.get("Name: Somi", {})

            # Create the prompt for the new persona
            prompt = f"""
You are a personality editor for an AI assistant. Your task is to create a new personality configuration based on the user’s input, using the provided template structure. The template is provided below in JSON format to show the expected structure. You must output a JSON object containing ONLY the new personality with the key "Name: {persona_name}", in the EXACT same structure as the template. Do NOT include other personas, do NOT modify existing personas, and do NOT include additional text, comments, or deviations from the structure. Ensure each list (physicality, experience, inhibitions, hobbies, behaviors) contains EXACTLY 12 items, with behaviors containing 12 single-word traits.

Template Structure (use this structure, but fill with new data for a {prompt_input}):
{json.dumps({"Name: Somi": template_persona}, indent=4)}

User Input for New Personality:
"{prompt_input}"

Create a new personality for the AI as a {prompt_input}. Set the 'role' to a suitable role for a {prompt_input} and 'temperature' to an appropriate value between 0.5 and 1.0. Fill each list (physicality, experience, inhibitions, hobbies, behaviors) with traits and actions relevant to a {prompt_input}. Output ONLY the new personality configuration in JSON format, like this:
{{
    "Name: {persona_name}": {{...}}
}}
"""
            print(f"Sending prompt to Ollama for new persona: {prompt_input}")
            response = self.ollama.generate(model="codegemma", prompt=prompt)
            raw_output = response["response"].strip()
            print("Received raw response from Ollama:")
            print(raw_output)

            # Strip Markdown code block markers (```json ... ```) if present
            if raw_output.startswith("```json"):
                raw_output = raw_output[len("```json"):].strip()
            if raw_output.endswith("```"):
                raw_output = raw_output[:-len("```")].strip()

            # Validate and parse the JSON output
            if not raw_output:
                raise ValueError("Empty response from Ollama")
            try:
                new_personality = json.loads(raw_output)
            except json.JSONDecodeError as je:
                print(f"Invalid JSON response from Ollama: {raw_output}")
                raise ValueError(f"Failed to parse Ollama response as JSON: {je}")

            # Validate that the response contains only the expected persona key
            if not isinstance(new_personality, dict) or persona_key not in new_personality:
                raise ValueError(f"Ollama response must contain only the key '{persona_key}', got: {list(new_personality.keys())}")
            if len(new_personality) != 1:
                raise ValueError(f"Ollama response must contain exactly one persona, got: {list(new_personality.keys())}")

            # Validate list lengths
            persona_data = new_personality[persona_key]
            for field in ["physicality", "experience", "inhibitions", "hobbies", "behaviors"]:
                if field in persona_data and len(persona_data[field]) != 12:
                    raise ValueError(f"Field '{field}' must contain exactly 12 items, got {len(persona_data[field])}")

            # Create backup before modifying
            self.personality_backup = self.current_personality.copy()

            # Add only the new persona to the current personality dictionary
            self.current_personality[persona_key] = persona_data
            self.persona_dropdown["values"] = list(self.current_personality.keys())
            self.persona_var.set(persona_key)

            # Update the GUI
            self.output_area.delete(1.0, tk.END)
            self.output_area.insert(tk.END, json.dumps({persona_key: persona_data}, indent=4))
            for field in self.fields:
                self.text_areas[field].delete(1.0, tk.END)
                value = persona_data.get(field, "")
                print(f"Inserting into {field} text area: {value}")
                if isinstance(value, list):
                    self.text_areas[field].insert(tk.END, "\n".join(value))
                else:
                    self.text_areas[field].insert(tk.END, str(value))

            messagebox.showinfo("Success", f"New personality '{persona_name}' added! Click 'Undo' to revert.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add new personality: {e}")

    def edit_existing_persona(self):
        if not self.current_persona_name:
            messagebox.showerror("Error", "Please select a persona to edit.")
            return

        # Get fields to edit
        edit_fields = simpledialog.askstring("Fields to Edit", f"Enter the fields to edit (comma-separated, e.g., 'description,physicality'), choose from: {', '.join(self.fields)}:")
        if not edit_fields:
            return
        fields_to_edit = [f.strip() for f in edit_fields.split(",") if f.strip() in self.fields]
        if not fields_to_edit:
            messagebox.showerror("Error", "No valid fields selected.")
            return

        prompt_input = simpledialog.askstring("Edit Prompt", f"Describe the changes for the fields {', '.join(fields_to_edit)} (e.g., 'Make description more adventurous, update physicality to reflect a mechanic'):")
        if not prompt_input:
            return

        try:
            # Get the current persona data
            persona_data = self.current_personality[self.current_persona_name]

            # Create the prompt to edit specific fields
            prompt = f"""
You are a personality editor for an AI assistant. Your task is to edit specific fields of an existing personality configuration based on the user’s input. The existing personality is provided below in JSON format. You must output the updated personality in the EXACT same JSON structure, editing ONLY the specified fields to reflect the user’s input. Do NOT add extra text, comments, or deviate from the structure. For list fields (physicality, experience, inhibitions, hobbies, behaviors), ensure EXACTLY 12 items, with behaviors containing 12 single-word traits.

Existing Personality:
{json.dumps({self.current_persona_name: persona_data}, indent=4)}

Fields to Edit:
{', '.join(fields_to_edit)}

User Input for Changes:
"{prompt_input}"

Update the specified fields ({', '.join(fields_to_edit)}) for the personality as described in the user input. Ensure the JSON structure remains identical, only modifying the content of the listed fields. For list fields, ensure exactly 12 items (except behaviors, which should have 12 single-word traits). Output the updated personality configuration in JSON format with the key "{self.current_persona_name}", with no additional text or deviations.
"""
            print(f"Sending prompt to Ollama for editing persona: {self.current_persona_name}")
            response = self.ollama.generate(model="codegemma", prompt=prompt)
            raw_output = response["response"].strip()
            print("Received raw response from Ollama:")
            print(raw_output)

            # Strip Markdown code block markers (```json ... ```) if present
            if raw_output.startswith("```json"):
                raw_output = raw_output[len("```json"):].strip()
            if raw_output.endswith("```"):
                raw_output = raw_output[:-len("```")].strip()

            # Validate and parse the JSON output
            if not raw_output:
                raise ValueError("Empty response from Ollama")
            try:
                updated_personality = json.loads(raw_output)
            except json.JSONDecodeError as je:
                print(f"Invalid JSON response from Ollama: {raw_output}")
                raise ValueError(f"Failed to parse Ollama response as JSON: {je}")

            # Validate that the response contains only the expected persona key
            if not isinstance(updated_personality, dict) or self.current_persona_name not in updated_personality:
                raise ValueError(f"Ollama response must contain only the key '{self.current_persona_name}', got: {list(updated_personality.keys())}")
            if len(updated_personality) != 1:
                raise ValueError(f"Ollama response must contain exactly one persona, got: {list(updated_personality.keys())}")

            # Create backup before modifying
            self.personality_backup = self.current_personality.copy()

            # Update the current personality dictionary
            self.current_personality[self.current_persona_name] = updated_personality[self.current_persona_name]

            # Update the GUI
            self.output_area.delete(1.0, tk.END)
            self.output_area.insert(tk.END, json.dumps({self.current_persona_name: updated_personality[self.current_persona_name]}, indent=4))

            for field in self.fields:
                self.text_areas[field].delete(1.0, tk.END)
                value = updated_personality[self.current_persona_name].get(field, "")
                print(f"Inserting into {field} text area: {value}")
                if isinstance(value, list):
                    self.text_areas[field].insert(tk.END, "\n".join(value))
                else:
                    self.text_areas[field].insert(tk.END, str(value))

            messagebox.showinfo("Success", f"Persona '{self.current_persona_name}' updated successfully! Click 'Undo' to revert.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to edit personality: {e}")

    def remove_persona(self):
        if not self.current_persona_name:
            messagebox.showerror("Error", "Please select a persona to remove.")
            return

        # Confirm deletion
        confirm = messagebox.askyesno("Confirm Removal", f"Are you sure you want to remove the persona '{self.current_persona_name}'? Changes will be permanent after saving.")
        if not confirm:
            return

        try:
            # Verify the persona exists
            if self.current_persona_name not in self.current_personality:
                raise ValueError(f"Persona '{self.current_persona_name}' does not exist.")

            # Create backup before modifying
            self.personality_backup = self.current_personality.copy()

            # Remove only the selected persona
            del self.current_personality[self.current_persona_name]

            # Update the dropdown and GUI
            persona_names = [key for key in self.current_personality.keys() if key.startswith("Name: ")]
            self.persona_dropdown["values"] = persona_names
            if persona_names:
                self.persona_var.set(persona_names[0])
                self.load_selected_persona(None)
            else:
                self.persona_var.set("")
                self.clear_gui()

            messagebox.showinfo("Success", f"Persona '{self.current_persona_name}' removed! Click 'Undo' to restore.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to remove persona: {e}")

    def undo_action(self):
        if not self.personality_backup:
            messagebox.showinfo("Info", "No action to undo.")
            return

        try:
            self.current_personality = self.personality_backup.copy()
            self.personality_backup = None  # Clear backup after undo
            persona_names = [key for key in self.current_personality.keys() if key.startswith("Name: ")]
            self.persona_dropdown["values"] = persona_names
            if persona_names:
                self.persona_var.set(persona_names[0])
                self.load_selected_persona(None)
            else:
                self.persona_var.set("")
                self.clear_gui()
            messagebox.showinfo("Success", "Last action undone.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to undo action: {e}")

    def save_personality(self):
        try:
            # Update current_personality with text area contents
            if self.current_persona_name:
                persona_data = {}
                for field in self.fields:
                    value = self.text_areas[field].get(1.0, tk.END).strip()
                    if field in ["physicality", "experience", "inhibitions", "hobbies", "behaviors"]:
                        persona_data[field] = [line for line in value.split("\n") if line.strip()]
                    elif field == "temperature":
                        try:
                            persona_data[field] = float(value) if value.strip() else 0.7
                            if not 0.0 <= persona_data[field] <= 1.0:
                                raise ValueError("Temperature must be between 0.0 and 1.0")
                        except ValueError as ve:
                            messagebox.showerror("Error", f"Invalid temperature value: {value}. Must be a number between 0.0 and 1.0")
                            return
                    else:
                        persona_data[field] = value
                self.current_personality[self.current_persona_name] = persona_data

            base_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(base_dir, "config", "personalC.json")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w') as f:
                json.dump(self.current_personality, f, indent=4)

            # Clear backup after saving (changes are permanent)
            self.personality_backup = None

            messagebox.showinfo("Success", f"Personality saved to {file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save personality: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = PersonaEditor(root)
    root.mainloop()