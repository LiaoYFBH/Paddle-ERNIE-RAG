import os
import time
import random
import logging
import pandas as pd
import argparse
from tqdm import tqdm
from dotenv import load_dotenv

from utils.ernie_client import ERNIEClient
from utils.vector_store import MilvusVectorStore
from backend import encode_name

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("evaluator")

# === 配置 ===
COLLECTION_UI_NAME = "stx_data"
SAMPLE_NUM = 300
TOP_K_RETRIEVAL = 50
DATASET_PATH = "final_test_dataset.csv"
MAX_CONTENT_LENGTH = 800  # 🌟 新增：Embedding 安全长度限制

class FinalSaverEvaluator:
    def __init__(self):
        load_dotenv()
        self.llm = ERNIEClient()
        real_name = encode_name(COLLECTION_UI_NAME)
        self.vector_store = MilvusVectorStore(
            uri=os.getenv("MILVUS_URI"),
            token=os.getenv("MILVUS_TOKEN"),
            collection_name=real_name,
            embedding_client=self.llm
        )
        logger.info(f"✅ 连接知识库: {COLLECTION_UI_NAME} | 样本数: {SAMPLE_NUM}")

    def generate_test_dataset(self, num_samples):
        logger.info("🚀 生成测试数据集...")
        res = self.vector_store.collection.query(
            expr="id > 0", 
            output_fields=["id", "content", "filename", "page"], 
            limit=3000
        )
        if not res: return []
        
        samples = random.sample(res, min(len(res), num_samples + 50))
        test_set = []
        
        for item in tqdm(samples, desc="LLM出题"):
            if len(test_set) >= num_samples: break
            content = item['content']
            if len(content) < 60: continue
            
            prompt = f"""Based on the following text snippet, generate a search query in English.
            Snippet: {content[:500]}
            Constraint: Output ONLY the question text in English.
            """
            try:
                question = self.llm.chat([{"role": "user", "content": prompt}])
                if question and "失败" not in question:
                    test_set.append({
                        "question": question,
                        "source_content": content,
                        "target_id": item['id'],
                        "target_filename": item['filename'],
                        "target_page": item['page']
                    })
            except: pass
        return test_set

    def load_existing_dataset(self, path):
        """加载已有数据集"""
        logger.info(f"📂 正在加载已有数据集: {path}")
        try:
            df = pd.read_csv(path, encoding="utf_8_sig")
            test_set = df.to_dict('records')
            logger.info(f"✅ 成功加载 {len(test_set)} 条测试数据")
            return test_set
        except Exception as e:
            logger.error(f"❌ 加载失败: {e}")
            return []

    def _truncate_content(self, text: str) -> str:
        """
        🌟 新增方法：截断超长文本
        """
        if not text or len(text) <= MAX_CONTENT_LENGTH:
            return text
        
        truncated = text[:MAX_CONTENT_LENGTH]
        
        # 尝试在句子边界截断
        last_period = max(
            truncated.rfind('。'),
            truncated.rfind('.'),
            truncated.rfind('\n')
        )
        
        if last_period > MAX_CONTENT_LENGTH * 0.8:
            truncated = truncated[:last_period + 1]
        
        return truncated

    def _preprocess_dataset(self, test_set: list) -> list:
        """
        🌟 新增方法：预处理数据集，截断超长文本
        """
        logger.info("🔧 正在预处理数据集...")
        truncated_count = 0
        
        for item in test_set:
            original_length = len(item.get('source_content', ''))
            
            # 截断 source_content
            if original_length > MAX_CONTENT_LENGTH:
                item['source_content'] = self._truncate_content(item['source_content'])
                truncated_count += 1
        
        if truncated_count > 0:
            logger.warning(f"⚠️  已截断 {truncated_count} 条超长文本 (超过 {MAX_CONTENT_LENGTH} 字符)")
        else:
            logger.info(f"✅ 所有文本长度均在安全范围内")
        
        return test_set

    def run(self, mode="auto"):
        """
        运行评估
        
        Args:
            mode: 'load' - 强制加载已有数据集
                  'generate' - 强制重新生成
                  'auto' - 自动判断（有则加载，无则生成）
        """
        # === 1. 数据集准备 ===
        test_set = []
        
        if mode == "load":
            logger.info("📂 模式: 加载已有数据集")
            test_set = self.load_existing_dataset(DATASET_PATH)
            if not test_set:
                logger.error("❌ 加载失败且模式为 'load'，退出程序")
                return
                
        elif mode == "generate":
            logger.info("🔄 模式: 强制重新生成数据集")
            test_set = self.generate_test_dataset(SAMPLE_NUM)
            if not test_set:
                logger.error("❌ 数据集生成失败")
                return
            
            logger.info(f"💾 正在保存题库到 {DATASET_PATH} ...")
            df_save = pd.DataFrame(test_set)
            df_save.to_csv(DATASET_PATH, index=False, encoding="utf_8_sig")
            logger.info("✅ 题库保存成功！")
            
        else:  # mode == "auto"
            logger.info("🤖 模式: 自动判断")
            if os.path.exists(DATASET_PATH):
                logger.info(f"✅ 检测到已有数据集: {DATASET_PATH}")
                test_set = self.load_existing_dataset(DATASET_PATH)
                
            if not test_set:
                logger.info("⚠️  未找到或加载失败，自动切换为生成模式")
                test_set = self.generate_test_dataset(SAMPLE_NUM)
                if test_set:
                    df_save = pd.DataFrame(test_set)
                    df_save.to_csv(DATASET_PATH, index=False, encoding="utf_8_sig")
                    logger.info("✅ 题库保存成功！")
        
        if not test_set:
            logger.error("❌ 无可用数据集，退出")
            return
        
        # 🌟 关键修改：在评估前统一预处理数据集
        test_set = self._preprocess_dataset(test_set)
        
        # === 2. 开始评测 ===
        stats = {
            "physical_recall": 0,
            "doc_recall": 0,
            "page_recall": 0,
            "chunk_recall": 0
        }
        
        logger.info(f"🚀 开始全链路评估...")
        
        for item in tqdm(test_set, desc="评估中"):
            # === 测试 1: (向量搜向量) ===
            try:
                content_emb = self.vector_store.embedding_client.get_embedding(item['source_content'])
                res_phy = self.vector_store.collection.search(
                    data=[content_emb], anns_field="embedding", param={"metric_type": "L2", "params": {}}, 
                    limit=TOP_K_RETRIEVAL, output_fields=["id"]
                )
                ids_phy = [h.id for h in res_phy[0]]
                if item['target_id'] in ids_phy:
                    stats['physical_recall'] += 1
            except: pass

            # === 测试 2: 真实 QA 检索 (Hybrid Search) ===
            try:
                results = self.vector_store.search(item['question'], top_k=TOP_K_RETRIEVAL)
                
                # A. 文档级
                filenames = [r.get('filename') for r in results]
                if item['target_filename'] in filenames:
                    stats['doc_recall'] += 1
                    
                    # B. 页级
                    for r in results:
                        if r.get('filename') == item['target_filename'] and r.get('page') == item['target_page']:
                            stats['page_recall'] += 1
                            break
                
                # C. 切片级
                ids = [r.get('id') for r in results]
                if item['target_id'] in ids:
                    stats['chunk_recall'] += 1
            except: pass
            
        # === 输出结果 ===
        total = len(test_set)
        def get_pct(k): return (stats[k] / total) * 100
        
        print("\n" + "="*80)
        print("📊 系统性能全景图 (System Performance Panorama)")
        print("="*80)
        print(f"{'Metric Layer':<25} | {'hit rate@50':<10} | {'Interpretation'}")
        print("-" * 80)
        print(f"{'1. Vector Self-Recall':<25} | {get_pct('physical_recall'):6.2f}%    | 原文检索原文")
        print("-" * 80)
        print(f"{'2. Document Recall':<25} | {get_pct('doc_recall'):6.2f}%    | 宏观定位")
        print(f"{'3. Page Recall':<25} | {get_pct('page_recall'):6.2f}%    | 中观定位")
        print(f"{'4. Chunk Recall':<25} | {get_pct('chunk_recall'):6.2f}%    | 微观定位")
        print("="*80)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF QA 系统性能评估工具")
    parser.add_argument(
        "--mode", 
        type=str, 
        choices=["load", "generate", "auto"], 
        default="auto",
        help="数据集模式: load=加载已有 | generate=重新生成 | auto=自动判断(默认)"
    )
    
    args = parser.parse_args()
    
    eval = FinalSaverEvaluator()
    eval.run(mode=args.mode)