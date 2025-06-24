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

# Suppress pdfplumber warnings by adjusting logging
logging.getLogger("pdfplumber").setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class RAGHandler:
    def __init__(self, storage_path="rag_data", nlist=100):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)
        self.vector_file = self.storage_path / "rag_vectors.faiss"
        self.text_file = self.storage_path / "rag_texts.json"
        self.precomputed_query_file = self.storage_path / "precomputed_queries.json"
        self.model = SentenceTransformer('all-MiniLM-L12-v2')  # Optimized model
        self.index = None
        self.texts = []
        self.pdf_folder = Path("pdfs")
        self.nlist = nlist  # Number of clusters for IndexIVFFlat
        self.query_cache = {}  # In-memory cache for query embeddings
        self.precomputed_queries = self._load_precomputed_queries()
        self.embedding_buffer = []  # Buffer for batching embeddings
        self._load_indices()

    def _load_precomputed_queries(self):
        """Load precomputed query embeddings from a JSON file."""
        if self.precomputed_query_file.exists():
            try:
                with open(self.precomputed_query_file, "r") as f:
                    data = json.load(f)
                    return {k: np.array(v, dtype=np.float32) for k, v in data.items()}
            except Exception as e:
                logger.warning(f"Failed to load precomputed queries: {str(e)}")
        return {}

    def _load_indices(self):
        """Load existing FAISS index and text metadata."""
        if self.vector_file.exists() and self.text_file.exists() and self.text_file.stat().st_size > 0:
            try:
                self.index = faiss.read_index(str(self.vector_file))
                sample_embedding = self.model.encode(["test"])[0]
                if self.index.d != sample_embedding.shape[0]:
                    logger.warning("Embedding dimension mismatch. Rebuilding index.")
                    self.index = None
                    self.texts = []
                else:
                    with open(self.text_file, "r") as f:
                        self.texts = json.load(f)
                    logger.info(f"Loaded studied data: {len(self.texts)} entries")
            except Exception as e:
                logger.warning(f"Failed to load studied data: {str(e)}")
                self.index = None
                self.texts = []

    def store(self, content, source):
        """Buffer content and its embedding for batch processing."""
        embedding = self.model.encode([content])[0]
        self.embedding_buffer.append((embedding, content, source))
        if len(self.embedding_buffer) >= self.nlist:
            self._flush_buffer()

    def _flush_buffer(self):
        """Process buffered embeddings and store in FAISS and JSON."""
        if not self.embedding_buffer:
            return

        embeddings = np.array([item[0] for item in self.embedding_buffer], dtype=np.float32)
        contents = [item[1] for item in self.embedding_buffer]
        sources = [item[2] for item in self.embedding_buffer]

        if self.index is None:
            dim = embeddings.shape[1]
            if len(embeddings) >= self.nlist:
                # Use IndexIVFFlat if enough vectors
                quantizer = faiss.IndexFlatL2(dim)
                self.index = faiss.IndexIVFFlat(quantizer, dim, self.nlist)
                try:
                    self.index.train(embeddings)
                    logger.info(f"Trained IndexIVFFlat with {len(embeddings)} vectors")
                except Exception as e:
                    logger.warning(f"Failed to train IndexIVFFlat: {str(e)}. Falling back to IndexFlatL2")
                    self.index = faiss.IndexFlatL2(dim)
            else:
                # Fall back to IndexFlatL2 if insufficient vectors
                logger.warning(f"Insufficient vectors ({len(embeddings)} < {self.nlist}). Using IndexFlatL2")
                self.index = faiss.IndexFlatL2(dim)
            self.texts = []

        self.index.add(embeddings)
        self.texts.extend({"content": content, "source": source} for content, source in zip(contents, sources))
        faiss.write_index(self.index, str(self.vector_file))
        with open(self.text_file, "w") as f:
            json.dump(self.texts, f)
        self.embedding_buffer = []
        logger.info(f"Stored {len(embeddings)} items in FAISS index")

    def retrieve(self, query, k=3):
        """Retrieve top-k relevant content using cached or precomputed embeddings."""
        if not self.index or not self.texts:
            logger.warning("No studied data available.")
            return []

        if query in self.precomputed_queries:
            query_embedding = self.precomputed_queries[query]
            logger.info(f"Using precomputed embedding for query: {query}")
        elif query in self.query_cache:
            query_embedding = self.query_cache[query]
            logger.info(f"Using cached embedding for query: {query}")
        else:
            query_embedding = self.model.encode([query])[0]
            self.query_cache[query] = query_embedding
            logger.info(f"Encoded and cached new query: {query}")

        if isinstance(self.index, faiss.IndexIVFFlat):
            self.index.nprobe = 10
        distances, indices = self.index.search(np.array([query_embedding], dtype=np.float32), k)
        return [self.texts[idx] for idx in indices[0] if idx < len(self.texts)]

    def get_embedding_model(self):
        """Return the SentenceTransformer model."""
        return self.model

    def precompute_queries(self, queries):
        """Precompute embeddings for a list of queries and save to file."""
        embeddings = self.model.encode(queries)
        self.precomputed_queries.update({query: embedding.tolist() for query, embedding in zip(queries, embeddings)})
        with open(self.precomputed_query_file, "w") as f:
            json.dump({k: v.tolist() for k, v in self.precomputed_queries.items()}, f)
        logger.info(f"Precomputed and saved embeddings for {len(queries)} queries")

    async def study_pdfs(self):
        """Extract and store text from PDFs."""
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
        self._flush_buffer()  # Ensure remaining buffered embeddings are stored

    async def study_websites(self):
        """Scrape and store content from websites."""
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
        self._flush_buffer()  # Ensure remaining buffered embeddings are stored

    async def ingest_pdfs(self):
        """Wrapper for studying PDFs."""
        await self.study_pdfs()

    async def ingest_websites(self):
        """Wrapper for studying websites."""
        await self.study_websites()

    async def study(self, source_type="pdfs"):
        """Study data from specified source type."""
        if source_type == "pdfs":
            await self.study_pdfs()
        elif source_type == "websites":
            await self.study_websites()
        else:
            logger.error(f"Unknown source type: {source_type}")

if __name__ == "__main__":
    # Suppress Hugging Face symlink warning
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    
    rag = RAGHandler(nlist=10)  # Reduced nlist for testing with small datasets
    common_queries = ["What is RAG?", "How to optimize vector search?", "PDF processing techniques"]
    rag.precompute_queries(common_queries)
    asyncio.run(rag.study("pdfs"))