# gui/speechgui.py
import tkinter as tk
from tkinter import messagebox, Toplevel, Entry, OptionMenu, StringVar, Checkbutton, IntVar
import subprocess
import threading
import queue
import importlib
import os
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Import audiosettings
try:
    from config import audiosettings
except ImportError as e:
    logger.error(f"Failed to import audiosettings: {str(e)}")
    raise ImportError("Could not import config.audiosettings. Ensure the file exists and is accessible.")

def alex_ai_start(app):
    """Start the Alex-AI speech pipeline with selected agent and optional use-studies flag."""
    logger.info("Initiating Alex-AI Start...")
    app.alex_start_button.config(state=tk.DISABLED)
    app.alex_stop_button.config(state=tk.NORMAL)

    # Open subwindow for agent selection
    name_window = Toplevel(app.root)
    name_window.title("Select Alex-AI Agent")
    name_window.geometry("400x250")

    # Agent Name Selection
    tk.Label(name_window, text="Agent Name:", width=15, anchor="w").pack(pady=5)
    name_var = StringVar(value=app.agent_names[0])  # Default to first agent name
    name_menu = OptionMenu(name_window, name_var, *app.agent_names)
    name_menu.config(width=37)
    name_menu.pack(pady=5)

    # Use Studies Checkbox
    use_studies_var = IntVar(value=1)  # Default checked
    tk.Checkbutton(name_window, text="Use Studies (RAG)", variable=use_studies_var).pack(pady=5)

    def start_speech():
        """Start the speech pipeline with the selected agent."""
        selected_name = name_var.get()
        agent_key = app.agent_keys[app.agent_names.index(selected_name)]

        # Validate agent name
        if not app.validate_agent_name(agent_key):
            app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Invalid agent name: {selected_name}\n")
            app.output_area.see(tk.END)
            messagebox.showerror("Error", f"Invalid agent name: {selected_name}")
            name_window.destroy()
            app.alex_start_button.config(state=tk.NORMAL)
            app.alex_stop_button.config(state=tk.DISABLED)
            return

        use_studies = bool(use_studies_var.get())
        app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Starting Alex-AI with {selected_name} {'using studies' if use_studies else ''}...\n")
        app.output_area.see(tk.END)
        app.root.update()

        def run_speech_pipeline():
            try:
                if app.alex_process and app.alex_process.poll() is None:
                    app.root.after(0, lambda: app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Alex-AI is already running.\n"))
                    app.root.after(0, lambda: messagebox.showinfo("Info", "Alex-AI is already running!"))
                    app.root.after(0, lambda: app.alex_start_button.config(state=tk.NORMAL))
                    app.root.after(0, lambda: app.output_area.see(tk.END))
                    return

                # Construct command with optional --use-studies flag
                cmd = ["python", "speech.py", "--name", agent_key] + (["--use-studies"] if use_studies else [])
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"  # Ensure unbuffered output

                # Start the subprocess
                app.alex_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    universal_newlines=True,
                    bufsize=1,
                    env=env
                )
                logger.info(f"Started Alex-AI process with PID {app.alex_process.pid}")

                # Start thread to read stderr
                stderr_queue = queue.Queue()
                threading.Thread(target=read_stderr, args=(app.alex_process, stderr_queue), daemon=True).start()

                # Start checking stderr queue
                app.root.after(100, lambda: check_stderr_queue(app, stderr_queue))

                # Check process status after 1 second
                app.root.after(1000, lambda: check_process_status(app, selected_name, stderr_queue))

            except Exception as e:
                logger.error(f"Unexpected error starting Alex-AI: {str(e)}")
                app.root.after(0, lambda: app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected error: {str(e)}\n"))
                app.root.after(0, lambda: messagebox.showerror("Error", f"Unexpected error: {str(e)}"))
                app.alex_process = None
                app.root.after(0, lambda: app.alex_start_button.config(state=tk.NORMAL))
                app.root.after(0, lambda: app.alex_stop_button.config(state=tk.DISABLED))
                app.root.after(0, lambda: app.output_area.see(tk.END))

        threading.Thread(target=run_speech_pipeline, daemon=True).start()
        name_window.destroy()

    def cancel():
        name_window.destroy()
        app.alex_start_button.config(state=tk.NORMAL)
        app.alex_stop_button.config(state=tk.DISABLED)

    tk.Button(name_window, text="Start", command=start_speech).pack(side=tk.LEFT, padx=10, pady=10)
    tk.Button(name_window, text="Cancel", command=cancel).pack(side=tk.LEFT, padx=10, pady=10)

def read_stderr(process, q):
    """Read stderr lines and put them into the queue."""
    while True:
        line = process.stderr.readline()
        if line:
            q.put(line.strip())
        else:
            break

def check_stderr_queue(app, q):
    """Check the stderr queue and update output_area."""
    try:
        while not q.empty():
            line = q.get_nowait()
            app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Alex-AI stderr: {line}\n")
            app.output_area.see(tk.END)
    except queue.Empty:
        pass
    app.root.after(100, lambda: check_stderr_queue(app, q))

def check_process_status(app, selected_name, stderr_queue):
    """Check if the Alex-AI process is still running after startup."""
    if app.alex_process and app.alex_process.poll() is None:
        app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Alex-AI started successfully with {selected_name}.\n")
        messagebox.showinfo("Success", f"Alex-AI started successfully with {selected_name}!")
    else:
        error_msg = "Alex-AI failed to start. Check output log for details."
        app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}\n")
        messagebox.showerror("Error", error_msg)
        app.alex_process = None
        app.alex_start_button.config(state=tk.NORMAL)
        app.alex_stop_button.config(state=tk.DISABLED)
    app.output_area.see(tk.END)
    app.root.update()

def alex_ai_stop(app):
    """Stop the running Alex-AI speech pipeline process."""
    logger.info("Initiating Alex-AI Stop...")
    app.alex_stop_button.config(state=tk.DISABLED)

    app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Stopping Alex-AI...\n")
    app.output_area.see(tk.END)
    app.root.update()

    def stop_speech_pipeline():
        try:
            if not app.alex_process or app.alex_process.poll() is not None:
                app.root.after(0, lambda: app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] No Alex-AI process is running.\n"))
                app.root.after(0, lambda: messagebox.showinfo("Info", "No Alex-AI process is running!"))
            else:
                app.alex_process.terminate()
                try:
                    app.alex_process.wait(timeout=5)
                    app.root.after(0, lambda: app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Alex-AI stopped successfully.\n"))
                    app.root.after(0, lambda: messagebox.showinfo("Success", "Alex-AI stopped successfully!"))
                except subprocess.TimeoutExpired:
                    logger.warning("Alex-AI process did not terminate gracefully, killing...")
                    app.alex_process.kill()
                    app.alex_process.wait(timeout=2)
                    app.root.after(0, lambda: app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Alex-AI forcefully stopped.\n"))
                    app.root.after(0, lambda: messagebox.showinfo("Success", "Alex-AI forcefully stopped!"))
                app.alex_process = None
            app.root.after(0, lambda: app.output_area.see(tk.END))
            app.root.after(0, lambda: app.root.update)
        except Exception as e:
            logger.error(f"Error stopping Alex-AI: {str(e)}")
            app.root.after(0, lambda: app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Error stopping Alex-AI: {str(e)}\n"))
            app.root.after(0, lambda: messagebox.showerror("Error", f"Error stopping Alex-AI: {str(e)}"))
        finally:
            app.root.after(0, lambda: app.alex_start_button.config(state=tk.NORMAL))
            app.root.after(0, lambda: app.alex_stop_button.config(state=tk.DISABLED))
            app.root.after(0, lambda: app.output_area.see(tk.END))
            app.root.after(0, app.root.update)

    threading.Thread(target=stop_speech_pipeline, daemon=True).start()

def audio_settings(app):
    """Display and edit audio settings from config/audiosettings.py."""
    logger.info("Opening Audio Settings subwindow...")
    settings_window = Toplevel(app.root)
    settings_window.title("Audio Settings")
    settings_window.geometry("600x500")

    def display_settings():
        try:
            # Wake Words
            tk.Label(settings_window, text="Wake Words:", width=15, anchor="w").pack(pady=5)
            wake_words_text = ", ".join(audiosettings.WAKE_WORDS) if audiosettings.WAKE_WORDS else "None"
            tk.Label(settings_window, text=wake_words_text, wraplength=500, anchor="w").pack(pady=5)

            # Cessation Words
            tk.Label(settings_window, text="Cessation Words:", width=15, anchor="w").pack(pady=5)
            cessation_words_text = ", ".join(audiosettings.CESSATION_WORDS) if audiosettings.CESSATION_WORDS else "None"
            tk.Label(settings_window, text=cessation_words_text, wraplength=500, anchor="w").pack(pady=5)

            # Whisper Model
            tk.Label(settings_window, text="Whisper Model:", width=15, anchor="w").pack(pady=5)
            whisper_model_text = audiosettings.WHISPER_MODEL if audiosettings.WHISPER_MODEL else "Not set"
            tk.Label(settings_window, text=whisper_model_text, anchor="w").pack(pady=5)

            # Ollama Model
            tk.Label(settings_window, text="Ollama Model:", width=15, anchor="w").pack(pady=5)
            ollama_model_text = audiosettings.OLLAMA_MODEL if audiosettings.OLLAMA_MODEL else "Not set"
            tk.Label(settings_window, text=ollama_model_text, anchor="w").pack(pady=5)

            # TTS Model
            tk.Label(settings_window, text="TTS Model:", width=15, anchor="w").pack(pady=5)
            tts_model_text = audiosettings.TTS_MODEL if audiosettings.TTS_MODEL else "Not set"
            tk.Label(settings_window, text=tts_model_text, anchor="w").pack(pady=5)

            # Cleanup Interval
            tk.Label(settings_window, text="Cleanup Interval:", width=15, anchor="w").pack(pady=5)
            cleanup_interval_text = f"{audiosettings.CLEANUP_INTERVAL} seconds" if audiosettings.CLEANUP_INTERVAL else "Not set"
            tk.Label(settings_window, text=cleanup_interval_text, anchor="w").pack(pady=5)

            # Greeting Message
            tk.Label(settings_window, text="Greeting Message:", width=15, anchor="w").pack(pady=5)
            greeting_message_text = audiosettings.GREETING_MESSAGE if audiosettings.GREETING_MESSAGE else "Not set"
            tk.Label(settings_window, text=greeting_message_text, wraplength=500, anchor="w").pack(pady=5)

        except AttributeError as e:
            logger.error(f"Error accessing audiosettings attributes: {str(e)}")
            messagebox.showerror("Error", f"Failed to load audio settings: {str(e)}")
            settings_window.destroy()
            return

    display_settings()

    def edit_settings():
        edit_window = Toplevel(settings_window)
        edit_window.title("Edit Audio Settings")
        edit_window.geometry("600x500")

        tk.Label(edit_window, text="Wake Words (comma-separated):", width=25, anchor="w").pack(pady=5)
        wake_words_entry = tk.Entry(edit_window, width=60)
        wake_words_entry.insert(0, ", ".join(audiosettings.WAKE_WORDS))
        wake_words_entry.pack(pady=5)

        tk.Label(edit_window, text="Cessation Words (comma-separated):", width=25, anchor="w").pack(pady=5)
        cessation_words_entry = tk.Entry(edit_window, width=60)
        cessation_words_entry.insert(0, ", ".join(audiosettings.CESSATION_WORDS))
        cessation_words_entry.pack(pady=5)

        tk.Label(edit_window, text="Whisper Model:", width=25, anchor="w").pack(pady=5)
        whisper_model_entry = tk.Entry(edit_window, width=60)
        whisper_model_entry.insert(0, audiosettings.WHISPER_MODEL)
        whisper_model_entry.pack(pady=5)

        tk.Label(edit_window, text="Ollama Model:", width=25, anchor="w").pack(pady=5)
        ollama_model_entry = tk.Entry(edit_window, width=60)
        ollama_model_entry.insert(0, audiosettings.OLLAMA_MODEL)
        ollama_model_entry.pack(pady=5)

        tk.Label(edit_window, text="TTS Model:", width=25, anchor="w").pack(pady=5)
        tts_model_entry = tk.Entry(edit_window, width=60)
        tts_model_entry.insert(0, audiosettings.TTS_MODEL)
        tts_model_entry.pack(pady=5)

        tk.Label(edit_window, text="Cleanup Interval (seconds):", width=25, anchor="w").pack(pady=5)
        cleanup_interval_entry = tk.Entry(edit_window, width=60)
        cleanup_interval_entry.insert(0, str(audiosettings.CLEANUP_INTERVAL))
        cleanup_interval_entry.pack(pady=5)

        tk.Label(edit_window, text="Greeting Message:", width=25, anchor="w").pack(pady=5)
        greeting_message_entry = tk.Entry(edit_window, width=60)
        greeting_message_entry.insert(0, audiosettings.GREETING_MESSAGE)
        greeting_message_entry.pack(pady=5)

        def save_settings():
            new_wake_words = [word.strip() for word in wake_words_entry.get().split(",") if word.strip()]
            new_cessation_words = [word.strip() for word in cessation_words_entry.get().split(",") if word.strip()]
            new_whisper_model = whisper_model_entry.get().strip()
            new_ollama_model = ollama_model_entry.get().strip()
            new_tts_model = tts_model_entry.get().strip()
            new_cleanup_interval = cleanup_interval_entry.get().strip()
            new_greeting_message = greeting_message_entry.get().strip()

            # Validate inputs
            if not all([new_wake_words, new_cessation_words, new_whisper_model, new_ollama_model,
                        new_tts_model, new_cleanup_interval, new_greeting_message]):
                messagebox.showwarning("Warning", "All fields must be filled.")
                return
            try:
                int(new_cleanup_interval)
            except ValueError:
                messagebox.showwarning("Warning", "Cleanup Interval must be a number.")
                return

            try:
                settings_path = "config/audiosettings.py"
                with open(settings_path, "r") as f:
                    lines = f.readlines()

                new_lines = []
                in_wake_words = False
                in_cessation_words = False
                for line in lines:
                    if line.strip().startswith("WAKE_WORDS"):
                        in_wake_words = True
                        new_lines.append("WAKE_WORDS = [\n")
                        for word in new_wake_words:
                            new_lines.append(f'    "{word}",\n')
                        new_lines[-1] = new_lines[-1].rstrip(",\n") + "\n"
                        new_lines.append("]\n")
                        continue
                    if line.strip().startswith("CESSATION_WORDS"):
                        in_cessation_words = True
                        new_lines.append("CESSATION_WORDS = [\n")
                        for word in new_cessation_words:
                            new_lines.append(f'    "{word}",\n')
                        new_lines[-1] = new_lines[-1].rstrip(",\n") + "\n"
                        new_lines.append("]\n")
                        continue
                    if line.strip().startswith("WHISPER_MODEL"):
                        new_lines.append(f'WHISPER_MODEL = "{new_whisper_model}"\n')
                        continue
                    if line.strip().startswith("OLLAMA_MODEL"):
                        new_lines.append(f'OLLAMA_MODEL = "{new_ollama_model}"\n')
                        continue
                    if line.strip().startswith("TTS_MODEL"):
                        new_lines.append(f'TTS_MODEL = "{new_tts_model}"\n')
                        continue
                    if line.strip().startswith("CLEANUP_INTERVAL"):
                        new_lines.append(f"CLEANUP_INTERVAL = {new_cleanup_interval}\n")
                        continue
                    if line.strip().startswith("GREETING_MESSAGE"):
                        new_lines.append(f'GREETING_MESSAGE = "{new_greeting_message}"\n')
                        continue
                    if in_wake_words or in_cessation_words:
                        if line.strip() == "]":
                            in_wake_words = False
                            in_cessation_words = False
                        continue
                    new_lines.append(line)

                with open(settings_path, "w") as f:
                    f.writelines(new_lines)

                importlib.reload(audiosettings)

                app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Audio settings updated successfully.\n")
                app.output_area.see(tk.END)
                messagebox.showinfo("Success", "Audio settings updated successfully!")
                edit_window.destroy()
                settings_window.destroy()
            except Exception as e:
                logger.error(f"Error updating audio settings: {str(e)}")
                app.output_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] Error updating audio settings: {str(e)}\n")
                app.output_area.see(tk.END)
                messagebox.showerror("Error", f"Error updating settings: {str(e)}")

        def cancel():
            edit_window.destroy()

        tk.Button(edit_window, text="Save", command=save_settings).pack(side=tk.LEFT, padx=10, pady=10)
        tk.Button(edit_window, text="Cancel", command=cancel).pack(side=tk.LEFT, padx=10, pady=10)

    tk.Button(settings_window, text="Edit", command=edit_settings).pack(pady=10)
    tk.Button(settings_window, text="Close", command=settings_window.destroy).pack(pady=10)