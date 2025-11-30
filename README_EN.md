[English](README_EN.md) | [中文](README.md)
# 🚀 Paddle-RAG: Multi-Document Analysis System with ERNIE 4.5 & PaddleOCR

## 📖 Introduction

This project is a high-performance Retrieval-Augmented Generation (RAG) system designed for complex academic papers and technical documents. Unlike traditional LangChain-based text splitting, this project deeply integrates the PaddleOCR (PP-StructureV3) intelligent document parsing engine, which can accurately recognize layout, tables, formulas, and images within PDFs.

Combined with the powerful semantic understanding of Baidu ERNIE 4.5 and the Milvus vector database, it achieves "What You Ask Is What You Get" with precise citation sourcing. The system supports Local Offline Mode (Milvus Lite), allowing deployment without complex servers.

## ✨ Key Features

- 🧠 Dual Baidu Engines:
      LLM: Powered by ERNIE-4.5-Turbo (via AIStudio API) for top-tier language understanding and generation.

- OCR: Integrated with PaddleOCR PP-StructureV3 for complex layout recovery and automatic chart extraction.

📂 Intelligent Document Processing:
        Auto-Deduplication: Automatically detects if a file already exists in the library during upload to avoid redundant computation.

Precise Page Indexing: Dynamic chunking strategy based on pages ensures answers include exact page citations (e.g., P1, P2), eliminating hallucinations.

⚡ Hybrid Search: Combines Dense Vector retrieval with Keyword retrieval, optimized by the RRF algorithm to significantly improve recall rates.

🖼️ Multimodal Context: Capable of not only answering with text but also extracting and displaying key charts and illustrations from the document as context supplements.
## 📸 Feature Showcase

### 1. Configuration & Local Mode
Supports one-click switching between **Cloud Milvus** and **Local Offline Mode (Milvus Lite)**. Simply configure your Baidu AIStudio and Qianfan API Keys to start, keeping data under your control.
![System Config](![系统配置](images/系统UI-3.png))

### 2. Knowledge Base & Intelligent Parsing
Powered by the PaddleOCR V3 parsing engine with support for Chinese/English model switching. The system features a real-time progress bar for transparent processing.
![Document List](images/系统UI-1-3.png)
### 3. Document Management
Supports multiple Collection management and viewing of all documents in the library. Supports macro Q&A on "All Documents" or deep reading focused on a "Single Document".

### 4. Precision Q&A with Citations
After asking a question, the system displays retrieved reference chunks marked with **precise page numbers** and **relevance scores**. 
![Q&A](images/演示4.png)

### 5. Charts & Knowledge Fusion
The system automatically extracts images and charts (e.g., knowledge graph structures, statistical charts) from PDFs. Relevant images are automatically displayed on the right side when answering questions to assist understanding.You can select the chart to ask questions.
![Chart Analysis1](images/系统UI-1-2.png)
![Chart Analysis2](images/系统UI-1-1.png)
## 📥 Quick Start (Pre-built Database)

To experience the system's capabilities immediately without manually parsing documents, you can download my **Pre-built Demo Database**.
This database contains processed academic papers on RAG/Short Text Clustering along with their extracted charts.
**Run**: Execute `python main.py`. The system will automatically load the demo data, and you can start asking questions right away!
## 📦 Installation & Usage

### Prerequisites

- Python 3.10+

- Baidu AIStudio Access Token

- Baidu Qianfan API Key

### 1. Clone Repository

```bash
git clone git@github.com:LiaoYFBH/Paddle-ERNIE-RAG.git
cd Paddle-ERNIE-RAG
```

### 2. Install Dependencies

```bash
# Basic requirements
pip install -r requirements.txt
```

### 3. Launch System

```bash
python main.py
```

After launch, the terminal will display the local access address (usually http://127.0.0.1:7860).

## ⚙️ Environment Configuration

You can fill in the "System Configuration" panel after starting the UI, or create a .env file in the project root:

```env
AISTUDIO_ACCESS_TOKEN=your_aistudio_token
QIANFAN_API_KEY=your_qianfan_key
OCR_API_URL=xxx
# Optional: If using Cloud Milvus
MILVUS_URI=https://...
MILVUS_TOKEN=...
```

## 📄 License

MIT License
