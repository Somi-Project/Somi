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
        self._load_indices()

    def _load_indices(self):
        if self.vector_file.exists() and self.text_file.exists() and self.text_file.stat().st_size > 0:
            try:
                self.index = faiss.read_index(str(self.vector_file))
                with open(self.text_file, "r") as f:
                    self.texts = json.load(f)
                logger.info(f"Loaded studied data: {len(self.texts)} entries")
            except Exception as e:
                logger.warning(f"Failed to load studied data: {str(e)}")
                self.index = None
                self.texts = []

    def store(self, content, source):
        embedding = self.model.encode([content])[0]
        if self.index is None:
            self.index = faiss.IndexFlatL2(embedding.shape[0])
            self.texts = []
        self.index.add(np.array([embedding], dtype=np.float32))
        self.texts.append({"content": content, "source": source})
        faiss.write_index(self.index, str(self.vector_file))
        with open(self.text_file, "w") as f:
            json.dump(self.texts, f)

    def retrieve(self, query, k=3):
        if not self.index or not self.texts:
            logger.warning("No studied data available.")
            return []
        query_embedding = self.model.encode([query])[0]
        distances, indices = self.index.search(np.array([query_embedding], dtype=np.float32), k)
        return [self.texts[idx] for idx in indices[0] if idx < len(self.texts)]

    def get_embedding_model(self):
        """Return the SentenceTransformer model for external use (e.g., memory storage)."""
        return self.model

    async def study_pdfs(self):
        if not self.pdf_folder.exists():
            logger.warning(f"No PDF folder found at {self.pdf_folder}")
            return
        for pdf_path in self.pdf_folder.glob("*.pdf"):
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text() or ""
                        if text.strip():
                            self.store(text, str(pdf_path))
                logger.info(f"Studied PDF: {pdf_path}")
            except Exception as e:
                logger.error(f"Error studying PDF {pdf_path}: {str(e)}")

    async def study_websites(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            for url in RAG_WEBSITES:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    content = await page.content()
                    self.store(content, url)
                    logger.info(f"Studied website: {url}")
                except Exception as e:
                    logger.error(f"Error studying website {url}: {str(e)}")
            await browser.close()

    async def ingest_pdfs(self):
        await self.study_pdfs()

    async def ingest_websites(self):
        await self.study_websites()

    async def study(self, source_type="pdfs"):
        if source_type == "pdfs":
            await self.study_pdfs()
        elif source_type == "websites":
            await self.study_websites()
        else:
            logger.error(f"Unknown source type: {source_type}")

if __name__ == "__main__":
    rag = RAGHandler()
    asyncio.run(rag.study("pdfs"))