import json
import random
import logging
import os
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler('agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class WordGameHandler:
    def __init__(self, game_file="game.json"):
        self.game_file = game_file
        self.game_state = {"game_type": "unknown", "questions": [], "answers": [], "target": None}
        # Dynamic game definitions (can be extended with new games)
        self.games = {
            "hangman": {
                "words": [
                    "mystery", "journey", "treasure", "painting", "sunrise", "laughter", "whisper", "mountain",
                    "riverbed", "shadows", "festival", "horizon", "silence", "gardenia", "carousel", "thunder",
                    "paradise", "whirlpool", "symphony", "emerald", "victory", "cascade", "twilight", "harmony",
                    "bravery", "oceanic", "sparkle", "wandering", "velvet", "crystal", "glacier", "phantom",
                    "serenity", "galaxy", "rhapsody", "illusion", "sapphire", "monsoon", "labyrinth", "paradox",
                    "radiance", "timeless", "vibrant", "blizzard", "serenade", "pinnacle", "chivalry", "solstice",
                    "euphoria", "miracle", "aurora", "saffron", "cascade", "journey", "treasure", "whisper",
                    "mountain", "riverbed", "festival", "silence", "gardenia", "thunder", "paradise", "whirlpool",
                    "symphony", "emerald", "victory", "twilight", "harmony", "bravery", "oceanic", "sparkle",
                    "wandering", "crystal", "glacier", "serenity", "galaxy", "rhapsody", "illusion", "sapphire",
                    "monsoon", "labyrinth", "paradox", "radiance", "timeless", "vibrant", "blizzard", "serenade",
                    "pinnacle", "chivalry", "solstice", "euphoria", "miracle", "aurora", "saffron"
                ],
                "init_state": lambda words: {
                    "word": random.choice(words),
                    "guesses_left": 6,
                    "guesses": [],
                    "current_state": "_" * len(random.choice(words))
                }
            }
            # Add new games here with their word lists and init_state functions
            # Example: "newgame": {"words": [...], "init_state": lambda words: {...}}
        }
        self.load_game_state()

    def load_game_state(self):
        """Load game state from game.json."""
        if os.path.exists(self.game_file):
            try:
                with open(self.game_file, "r") as f:
                    self.game_state = json.load(f)
                logger.info(f"Loaded game state from {self.game_file}")
            except Exception as e:
                logger.error(f"Error loading game state: {e}")
                self.game_state = {"game_type": "unknown", "questions": [], "answers": [], "target": None}
        else:
            self.game_state = {"game_type": "unknown", "questions": [], "answers": [], "target": None}

    def save_game_state(self):
        """Save game state to game.json."""
        try:
            with open(self.game_file, "w") as f:
                json.dump(self.game_state, f, indent=2)
            logger.info(f"Saved game state to {self.game_file}")
        except Exception as e:
            logger.error(f"Error saving game state: {e}")

    def clear_game_state(self):
        """Clear game.json and reset game state."""
        try:
            if os.path.exists(self.game_file):
                os.remove(self.game_file)
                logger.info(f"Cleared {self.game_file}")
            self.game_state = {"game_type": "unknown", "questions": [], "answers": [], "target": None}
        except Exception as e:
            logger.error(f"Error clearing game state: {e}")

    def start_game(self, game_type):
        """Initialize a new game with the specified game_type using predefined or dynamic settings."""
        if game_type not in self.games:
            logger.warning(f"Unknown game type: {game_type}")
            return False
        self.game_state = {
            "game_type": game_type,
            "questions": [],
            "answers": [],
            "target": None
        }
        game_config = self.games[game_type]
        self.game_state.update(game_config["init_state"](game_config["words"]))
        self.save_game_state()
        logger.info(f"Started {game_type} game with state: {self.game_state}")
        return True

    def get_game_context(self):
        """Generate context for the system prompt based on the current game state."""
        game_type = self.game_state.get("game_type", "hangman")
        questions = self.game_state.get("questions", [])
        answers = self.game_state.get("answers", [])
        context = ""
        for q, a in zip(questions, answers):
            context += f"question: {q}, answer: {a}\n"
        context = context.strip() or "No game history yet."

        if game_type == "hangman":
            return (
                f"Play Hangman. Word: {self.game_state.get('word', '******')}. "
                f"Current state: {self.game_state.get('current_state', '______')}. "
                f"Guesses left: {self.game_state.get('guesses_left', 6)}. "
                f"Previous guesses: {', '.join(self.game_state.get('guesses', [])) or 'None'}. "
                f"Game history: {context}. Respond to the user's guess or provide game status."
            )
        else:
            return f"Play a word game of type '{game_type}'. Use the game state: {json.dumps(self.game_state)}. Respond based on the game rules and user input."

    def process_response(self, response, prompt):
        """Process the model's response, extract game state update, and return cleaned response."""
        try:
            json_match = re.search(r"```json\n(.*?)\n```", response, re.DOTALL)
            if json_match:
                game_update = json.loads(json_match.group(1))
                self.game_state.update(game_update)
                self.save_game_state()
                response = re.sub(r"```json\n.*?\n```", "", response, flags=re.DOTALL).strip()
            return response
        except Exception as e:
            logger.error(f"Error processing game response: {e}")
            return response

    def process_game_input(self, prompt):
        """Process user input for the current game and update game state."""
        prompt_lower = prompt.lower().strip()
        game_type = self.game_state.get("game_type", "hangman")
        content = ""

        if game_type == "hangman":
            if not self.game_state.get("word"):  # Shouldn't happen due to start_game, but safeguard
                word = random.choice(self.games["hangman"]["words"])
                self.game_state.update({
                    "word": word,
                    "guesses_left": 6,
                    "guesses": [],
                    "current_state": "_" * len(word)
                })
                self.save_game_state()
                content = f"Let’s play Hangman! Word: {word}. Current state: {self.game_state['current_state']}. Guess a letter!"
            elif prompt_lower in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
                                "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z"]:
                guess = prompt_lower
                word = self.game_state.get("word", "")
                guesses = self.game_state.get("guesses", [])
                guesses_left = self.game_state.get("guesses_left", 6)
                current_state = list(self.game_state.get("current_state", "_" * len(word)))
                if guess in guesses:
                    content = f"You already guessed '{guess}'! Try another letter.\nCurrent state: {''.join(current_state)}. Guesses left: {guesses_left}."
                elif guess in word:
                    for i, letter in enumerate(word):
                        if letter == guess:
                            current_state[i] = guess
                    guesses.append(guess)
                    self.game_state.update({
                        "guesses": guesses,
                        "current_state": "".join(current_state),
                        "questions": self.game_state.get("questions", []) + [f"Guess: {guess}"],
                        "answers": self.game_state.get("answers", []) + ["Correct!"]
                    })
                    if "_" not in current_state:
                        content = f"You won! The word was '{word}'!"
                        self.clear_game_state()
                        return content, True
                    else:
                        content = f"Good guess! Current state: {''.join(current_state)}. Guesses left: {guesses_left}."
                else:
                    guesses.append(guess)
                    guesses_left -= 1
                    self.game_state.update({
                        "guesses": guesses,
                        "guesses_left": guesses_left,
                        "questions": self.game_state.get("questions", []) + [f"Guess: {guess}"],
                        "answers": self.game_state.get("answers", []) + ["Incorrect"]
                    })
                    if guesses_left <= 0:
                        content = f"Game over! The word was '{word}'."
                        self.clear_game_state()
                        return content, True
                    else:
                        content = f"Wrong guess! Current state: {''.join(current_state)}. Guesses left: {guesses_left}."
                self.save_game_state()
            else:
                content = f"Please guess a single letter for Hangman!"
        else:
            content = f"Unknown game type '{game_type}'. Please start a game with 'let's play hangman'."
        
        return content, False