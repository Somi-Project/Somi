import os
import logging
import asyncio
from pathlib import Path
import pdfplumber
from playwright.async_api import async_playwright
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import json
from config.settings import RAG_WEBSITES

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class RAGHandler:
    def __init__(self, storage_path="rag_data"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)
        self.vector_file = self.storage_path / "rag_vectors.faiss"
        self.text_file = self.storage_path / "rag_texts.json"
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.index = None
        self.texts = []
        self.pdf_folder = Path("pdfs")

    async def ingest_pdfs(self):
        if not self.pdf_folder.exists():
            logger.warning("No 'pdfs' folder found.")
            return

        pdf_texts = []
        for pdf_file in self.pdf_folder.glob("*.pdf"):
            try:
                with pdfplumber.open(pdf_file) as pdf:
                    text = " ".join(page.extract_text() or "" for page in pdf.pages)
                    if text.strip():
                        pdf_texts.append({"source": str(pdf_file), "content": text})
                        logger.info(f"Extracted text from {pdf_file}")
            except Exception as e:
                logger.error(f"Error processing {pdf_file}: {str(e)}")

        if pdf_texts:
            self._vectorize_and_store(pdf_texts)
            logger.info(f"Vectorized {len(pdf_texts)} PDFs.")

    async def ingest_websites(self):
        web_texts = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            for url in RAG_WEBSITES:
                try:
                    await page.goto(url, timeout=60000)
                    text = await page.evaluate(
                        """() => document.body.innerText"""
                    )
                    if text.strip():
                        web_texts.append({"source": url, "content": text})
                        logger.info(f"Scraped content from {url}")
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Error scraping {url}: {str(e)}")

            await browser.close()

        if web_texts:
            self._vectorize_and_store(web_texts)
            logger.info(f"Vectorized {len(web_texts)} websites.")

    def _vectorize_and_store(self, data):
        new_texts = [item["content"] for item in data]
        sources = [item["source"] for item in data]
        
        embeddings = self.model.encode(new_texts, show_progress_bar=True)
        
        if self.index is None:
            if self.vector_file.exists() and self.text_file.exists() and self.text_file.stat().st_size > 0:
                try:
                    self.index = faiss.read_index(str(self.vector_file))
                    with open(self.text_file, "r") as f:
                        self.texts = json.load(f)
                    logger.info(f"Loaded existing index and texts from {self.vector_file} and {self.text_file}")
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning(f"Failed to load {self.text_file} due to {str(e)}. Starting fresh.")
                    self.index = faiss.IndexFlatL2(embeddings.shape[1])
                    self.texts = []
            else:
                self.index = faiss.IndexFlatL2(embeddings.shape[1])
                self.texts = []

        self.index.add(np.array(embeddings, dtype=np.float32))
        self.texts.extend([{"source": src, "content": txt} for src, txt in zip(sources, new_texts)])

        faiss.write_index(self.index, str(self.vector_file))
        with open(self.text_file, "w") as f:
            json.dump(self.texts, f)
        logger.info(f"Stored {len(new_texts)} vectors in {self.vector_file}")

    def retrieve(self, query, k=3):
        if not self.index or not self.texts:
            logger.warning("No RAG data available.")
            return []

        query_embedding = self.model.encode([query])[0]
        distances, indices = self.index.search(np.array([query_embedding], dtype=np.float32), k)
        return [self.texts[idx] for idx in indices[0] if idx < len(self.texts)]

async def main():
    rag = RAGHandler()
    await rag.ingest_pdfs()
    await rag.ingest_websites()

if __name__ == "__main__":
    asyncio.run(main())