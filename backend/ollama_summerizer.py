import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

class local_ollama:
    def __init__(self, filename):
        
       
        self.ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        self.model = os.getenv("OLLAMA_MODEL", "mistral")

        print(f'Running Ollama: {self.model}')
      
        self.filename = "notebooklogs/notebook_experiments/" + self.find_file_match(filename)

        
        self.chunk_chars = int(os.getenv("SUM_CHUNK_CHARS", "12000"))      # size of each chunk
        self.chunk_overlap = int(os.getenv("SUM_CHUNK_OVERLAP", "1200"))   # overlap helps continuity

    def find_file_match(self, filename):
        registered_files = os.listdir("notebooklogs/notebook_experiments")
        base_name = os.path.splitext(os.path.basename(filename))[0]

        match = next(
            (f for f in registered_files if re.match(rf"^{re.escape(base_name)}(_io)?\.log$", f)),
            None
        )
        if not match:
            raise FileNotFoundError(f"No matching log file found for: {filename}")
        return match

    def read_file(self):
        with open(self.filename, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    
    def chunk_text(self, text):
        if len(text) <= self.chunk_chars:
            return [text]

        chunks = []
        step = self.chunk_chars - self.chunk_overlap
        for start in range(0, len(text), step):
            end = start + self.chunk_chars
            chunks.append(text[start:end])
            if end >= len(text):
                break
        return chunks

    
    def ollama_generate(self, prompt):
        r = requests.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 350,   
                    "num_ctx": 2048 
                }
            },
            timeout=300,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()

    # ---------- Prompts ----------
    def prompt_for_chunk(self, chunk, chunk_index, total_chunks):
        return f"""
            You are an expert software engineer and data scientist.
            You are summarizing PART {chunk_index}/{total_chunks} of a Jupyter notebook execution log.

            Write a structured partial summary with:
            - Cells/actions that ran (high level)
            - Key outputs/results (metrics, printed outputs, files created)
            - Errors/warnings (if any)
            - Notable data processing / model training steps

            Be concise but keep important technical details.

            LOG CHUNK:
        {chunk}
        """.strip()

    def prompt_for_final(self, partial_summaries):
        return f"""
        You are an expert software engineer and data scientist.

        You will be given multiple PARTIAL summaries of a notebook execution log.
        Combine them into ONE final report that is clear, detailed, and structured.

        Format:
        1) Executive summary (3–6 bullets)
        2) What was executed (ordered, grouped by theme)
        3) Key results/outputs
        4) Errors/warnings and likely causes
        5) Suggested next steps

        PARTIAL SUMMARIES:
        {partial_summaries}

        Now produce the FINAL report.
        """.strip()

    """
    def driver(self):
        text = self.read_file()
        chunks = self.chunk_text(text)

      
        if len(chunks) == 1:
            prompt = self.prompt_for_final(
                partial_summaries=self.ollama_generate(
                    self.prompt_for_chunk(chunks[0], 1, 1)
                )
            )
            return self.ollama_generate(prompt)

       
        partials = []
        for i, chunk in enumerate(chunks, start=1):
            p = self.prompt_for_chunk(chunk, i, len(chunks))
            partial_summary = self.ollama_generate(p)
            partials.append(f"--- PART {i}/{len(chunks)} ---\n{partial_summary}")

        
        combined = "\n\n".join(partials)
        final_prompt = self.prompt_for_final(combined)
        return self.ollama_generate(final_prompt)
    """
    def driver(self):
        text = self.read_file()
        chunks = self.chunk_text(text)

       
        partials = []
        for i, chunk in enumerate(chunks, start=1):
            p = self.prompt_for_chunk(chunk, i, len(chunks))
            partials.append(self.ollama_generate(p))

       
        def reduce_batch(batch, batch_id, total_batches):
            joined = "\n\n".join(batch)
            prompt = f"""
            You are combining PARTIAL summaries ({batch_id}/{total_batches}).

            Condense them into ONE concise technical summary:
            - key actions
            - results
            - errors
            - progress

            TEXT:
            {joined}
            """
            return self.ollama_generate(prompt)

        BATCH_SIZE = 3  
        reduced = []
        for i in range(0, len(partials), BATCH_SIZE):
            batch = partials[i:i+BATCH_SIZE]
            reduced.append(reduce_batch(batch, i//BATCH_SIZE + 1,
                                    (len(partials)+BATCH_SIZE-1)//BATCH_SIZE))

    
        final_prompt = self.prompt_for_final("\n\n".join(reduced))
        return self.ollama_generate(final_prompt)
