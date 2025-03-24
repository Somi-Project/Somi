import ollama
from config.settings import DEFAULT_MODEL, DEFAULT_TEMP
import json
import random
import logging
import faiss
from rag import RAGHandler

logging.getLogger("http.client").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

class SomiAgent:
    def __init__(self, name, use_studies=False):  # Changed from use_rag to use_studies
        self.name = name
        self.use_studies = use_studies  # Changed variable name
        with open("config/personalC.json", "r") as f:
            characters = json.load(f)
        character = characters.get(name, {})
        self.role = character.get("role", "assistant")
        self.temperature = character.get("temperature", DEFAULT_TEMP)
        self.description = character.get("description", "Generic assistant")
        self.physicality = character.get("physicality", [])
        self.memories = character.get("memories", [])
        self.inhibitions = character.get("inhibitions", [])
        self.hobbies = character.get("hobbies", [])
        self.behaviors = character.get("behaviors", [])
        self.model = DEFAULT_MODEL
        self.history = []
        self.rag = RAGHandler() if use_studies else None  # Updated condition
        if self.use_studies and self.rag:  # Updated condition
            self._load_rag_data()

    def _load_rag_data(self):
        """Load existing RAG data from files if available"""
        if self.rag.vector_file.exists() and self.rag.text_file.exists() and self.rag.text_file.stat().st_size > 0:
            try:
                self.rag.index = faiss.read_index(str(self.rag.vector_file))
                with open(self.rag.text_file, "r") as f:
                    self.rag.texts = json.load(f)
                logging.info(f"Loaded RAG data for {self.name}: {len(self.rag.texts)} entries")
            except Exception as e:
                logging.error(f"Failed to load RAG data: {str(e)}")
                self.rag.index = None
                self.rag.texts = []
        else:
            logging.warning("No valid RAG data files found to load.")

    def generate_system_prompt(self):
        behavior = random.choice(self.behaviors) if self.behaviors else "neutral"
        physicality = random.choice(self.physicality) if self.physicality else "generic assistant"
        memory = random.choice(self.memories) if self.memories else "no past"
        inhibition = random.choice(self.inhibitions) if self.inhibitions else "respond naturally"
        system_prompt = (
            f"You are {self.name}, a {behavior} {self.description}.\n"
            f"Physicality: {physicality}\n"
            f"Memory: {memory}\n"
            f"Inhibition: {inhibition}"
        )
        return system_prompt

    def generate_response(self, prompt):
        self.history.append({"role": "user", "content": prompt})
        recent_history = self.history[-5:]
        system_prompt = self.generate_system_prompt()
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        if recent_history:
            messages.append({"role": "system", "content": "Recent conversation:\n" + "\n".join(
                f"{msg['role']}: {msg['content']}" for msg in recent_history
            )})

        if self.use_studies and self.rag:  # Updated condition
            rag_context = self.rag.retrieve(prompt)
            if rag_context:
                context_text = "\n".join(f"Source: {item['source']}\nContent: {item['content'][:200]}..." for item in rag_context)
                messages.append({"role": "system", "content": f"RAG Context:\n{context_text}"})

        messages.append({"role": "user", "content": prompt})
        response = ollama.chat(
            model=self.model,
            messages=messages,
            options={"temperature": self.temperature}
        )
        content = response.get("message", {}).get("content", "")
        if content:
            self.history.append({"role": "assistant", "content": content})
        else:
            content = "Hmm, I’ve got nothing—maybe my coffee’s cold today!"
            self.history.append({"role": "assistant", "content": content})
        return content

    def generate_tweet(self):
        system_prompt = self.generate_system_prompt()
        hobby = random.choice(self.hobbies) if self.hobbies else "no hobby"
        user_prompt = f"Tweet about: {hobby}. Keep it under 280 characters."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        if self.use_studies and self.rag:  # Updated condition
            rag_context = self.rag.retrieve(hobby)
            if rag_context:
                context_text = "\n".join(f"Source: {item['source']}\nContent: {item['content'][:200]}..." for item in rag_context)
                messages.append({"role": "system", "content": f"RAG Context:\n{context_text}"})

        max_length = 280
        attempts = 0
        while attempts < 3:
            response = ollama.chat(
                model=self.model,
                messages=messages,
                options={"temperature": self.temperature, "max_tokens": 100}
            )
            content = response.get("message", {}).get("content", "")
            if content and len(content) <= max_length:
                return content
            if not content:
                content = "chalk dust’s got me stumped—check back after my coffee break!"
            print(f"Tweet length: {len(content)}. Too long or empty, retrying..." if len(content) > max_length else "Empty response, retrying...")
            attempts += 1
        return content[:max_length] if content else "short tweet fail—blame the projector!"