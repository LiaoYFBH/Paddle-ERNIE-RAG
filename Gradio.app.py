import os
import sys

os.environ["FLAGS_enable_pir_api"] = "0"           # 禁用 PIR 
os.environ["FLAGS_use_cin_compiler"] = "0"         # 禁用 CIN
os.environ["FLAGS_allocator_strategy"] = "auto_growth" 
os.environ["CUDA_VISIBLE_DEVICES"] = ""            # 强制 CPU
# === 🛑 [新增] 强力修复步骤 ===
import paddle  # 显式导入 paddle
try:
    paddle.set_device("cpu")  # 🔒 强制锁定全局设备为 CPU
    print("🔒 已强制设置 paddle.set_device('cpu')")
except Exception as e:
    print(f"⚠️ 警告: 强制设置 CPU 失败: {e}")
# ============================
import subprocess
import yaml
import logging
import shutil
import base64
import time
import socket
from pathlib import Path
import gradio as gr
from dotenv import load_dotenv
from PIL import Image
import numpy as np
import io

try:
    from paddlex import create_pipeline
    print("✅ PaddleX 导入成功")
except ImportError:
    print("❌ 未安装 paddlex，请运行: pip install paddlex")
    exit(1)
from pymilvus import utility, connections

from utils.vector_store import MilvusVectorStore
from utils.ernie_client import ERNIEClient
from utils.reranker_v2 import RerankerAndFilterV2

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
silence_libs = ["httpx", "httpcore", "urllib3", "asyncio", "pdf_qa", "gradio", "multipart", "PIL", "matplotlib", "ppocr", "paddle"]
for lib in silence_libs:
    logging.getLogger(lib).setLevel(logging.ERROR)

ASSET_DIR = "assets"
os.makedirs(ASSET_DIR, exist_ok=True)
CONFIG_DIR = "my_configs"
os.makedirs(CONFIG_DIR, exist_ok=True)

print("⚙️  系统启动中...")
pipeline_engine = None 
current_pipeline_lang = None  

def get_optimized_config_path(lang="ch"):
    """
    生成针对 CPU 优化的轻量级模型配置 (支持中英文切换)
    lang: "ch" (通用) 或 "en" (纯英文)
    """
    original_config_name = "PP-StructureV3.yaml"
    target_config_name = f"lightweight_structure_v3_{lang}.yaml"
    target_path = os.path.abspath(os.path.join(CONFIG_DIR, target_config_name))

    if not os.path.exists(os.path.join(CONFIG_DIR, original_config_name)):
        try:
            subprocess.run(
                ["paddlex", "--get_pipeline_config", "PP-StructureV3", "--save_path", CONFIG_DIR],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except: pass

    # 读取配置
    config_data = None
    src_yaml = os.path.join(CONFIG_DIR, original_config_name)
    if os.path.exists(src_yaml):
        try:
            with open(src_yaml, 'r', encoding='utf-8') as f: config_data = yaml.safe_load(f)
        except: pass
        
    # 保底配置
    if not config_data:
        config_data = {
            "pipeline_name": "PP-StructureV3",
            "SubModules": {
                "LayoutDetection": {"module_name": "layout_detection", "model_name": "PP-DocLayout-S", "batch_size": 1}
            },
            "SubPipelines": {
                "DocPreprocessor": {
                    "pipeline_name": "DocPreprocessor",
                    "SubModules": {
                        "DocOrientationClassify": {"module_name": "doc_orientation_classification", "model_name": "PP-LCNet_x1_0_doc_ori"},
                        "DocUnwarping": {"module_name": "doc_unwarping", "model_name": "UVDoc"}
                    }
                },
                "GeneralOCR": {
                    "pipeline_name": "OCR",
                    "text_type": "general",
                    "SubModules": {
                        "TextDetection": {"module_name": "text_detection", "model_name": "PP-OCRv4_mobile_det", "limit_side_len": 736},
                        "TextRecognition": {"module_name": "text_recognition", "model_name": "PP-OCRv4_mobile_rec"}
                    }
                },
                "TableRecognition": {
                    "pipeline_name": "TableRecognition",
                    "SubModules": {
                        "TableStructureRecognition": {"module_name": "table_structure_recognition", "model_name": "SLANeXt_wired"},
                        "TableClassification": {"module_name": "table_classification", "model_name": "PP-LCNet_x1_0_table_cls"}
                    }
                }
            }
        }
    def recursive_replace(d):
        if isinstance(d, dict):
            for k, v in d.items():
                if k == "model_name" and isinstance(v, str):
                    if "PP-DocLayout" in v: 
                        d[k] = "PP-DocLayout-S"
                    elif "PP-OCRv4" in v:
                        if "det" in v:
                            d[k] = "PP-OCRv4_mobile_det"
                        elif "rec" in v:
                            if lang == "en":
                                # 纯英文模式：使用英文专用识别模型
                                d[k] = "en_PP-OCRv4_mobile_rec"
                            else:
                                # 通用模式：使用默认中英文模型
                                d[k] = "PP-OCRv4_mobile_rec"
                    elif "PP-FormulaNet" in v: 
                        d[k] = "PP-FormulaNet-S"
                    elif "seal" in v:
                        if "det" in v: d[k] = "PP-OCRv4_mobile_seal_det"
                
                elif k == "limit_side_len" and isinstance(v, int) and v > 736:
                    d[k] = 736
                else:
                    recursive_replace(v)
        elif isinstance(d, list):
            for item in d: recursive_replace(item)
    
    recursive_replace(config_data)

    # 保存最终配置
    with open(target_path, 'w', encoding='utf-8') as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
    
    print(f"✅ 已生成 {lang} 模式配置: {target_path}")
    return target_path
def get_paddlex_pipeline(lang="ch"):
    """加载产线 (检测语言变更)"""
    global pipeline_engine, current_pipeline_lang
    
    if pipeline_engine is not None and current_pipeline_lang == lang:
        return pipeline_engine

    print(f"⏳ 正在初始化 PaddleX ({lang} 模式)...")
    
    
    # 获取对应语言的配置文件
    config_path = get_optimized_config_path(lang)
    
    try:
        pipeline_engine = None 
        
        pipeline_engine = create_pipeline(
            pipeline=config_path, 
            device="cpu",  
        )
        current_pipeline_lang = lang 
        print(f"🚀 PaddleX 引擎加载成功！(模式: {lang})")
    except Exception as e:
        print(f"❌ 引擎加载失败: {e}")
        import traceback
        traceback.print_exc()
        return None
            
    return pipeline_engine
ernie = None
milvus_store = None
reranker_filter = None
known_collections = {}
system_ready = False

def check_ready():
    if not system_ready: return False, "⚠️ 系统未连接"
    return True, ""

def initialize_system(aistudio_token, qianfan_key, milvus_uri, milvus_token):
    global ernie, milvus_store, reranker_filter, system_ready, known_collections

    aistudio_token = aistudio_token.strip() if aistudio_token else ""
    qianfan_key = qianfan_key.strip() if qianfan_key else ""
    milvus_uri = milvus_uri.strip() if milvus_uri else ""
    milvus_token = milvus_token.strip() if milvus_token else ""

    # 如果是本地文件模式 (.db)，则不需要校验 milvus_token
    is_local_mode = milvus_uri.endswith(".db")
    
    # 必填项检查：AIStudio、千帆、URI 必须有
    basic_check = all([aistudio_token, qianfan_key, milvus_uri])
    # Token检查：如果是服务器模式，则必须有 Token；如果是本地模式，Token 可为空
    token_check = True if is_local_mode else bool(milvus_token)

    if not (basic_check and token_check):
        return "❌ 请填写必要信息 (本地模式无需 Token，但在服务器模式下必填)", gr.update(), gr.update(), gr.update()

    try:
        os.environ["AISTUDIO_ACCESS_TOKEN"] = aistudio_token
        os.environ["QIANFAN_API_KEY"] = qianfan_key
        os.environ["MILVUS_URI"] = milvus_uri
        if milvus_token:
            os.environ["MILVUS_TOKEN"] = milvus_token
        else:
            os.environ.pop("MILVUS_TOKEN", None)

        ernie = ERNIEClient()
        reranker_filter = RerankerAndFilterV2()

        milvus_store = MilvusVectorStore(
            uri=milvus_uri,
            token=milvus_token, 
            collection_name="pdf_qa_collection_paddle_v3", 
            embedding_service_url="https://aistudio.baidu.com/llm/lmapi/v3",
            qianfan_api_key=aistudio_token
        )
        
        known_collections = {milvus_store.collection_name: milvus_store}
        try:
            scan_remote_collections()
        except: pass
        
        cols = list(known_collections.keys())
        default_col = cols[0] if cols else None
        
        system_ready = True
        get_paddlex_pipeline()
        return (
            "✅ 连接成功", 
            gr.update(choices=cols, value=default_col), 
            gr.update(choices=cols, value=default_col), 
            gr.update(choices=cols, value=default_col)
        )
        
    except Exception as e:
        return f"❌ 失败: {str(e)}", gr.update(), gr.update(), gr.update()

def scan_remote_collections():
    global known_collections
    try:
        alias = f"scan_{int(time.time())}"
        connections.connect(alias=alias, uri=os.environ.get("MILVUS_URI"), token=os.environ.get("MILVUS_TOKEN"))
        all_colls = utility.list_collections(using=alias)
        connections.disconnect(alias)
        for name in all_colls:
            if name not in known_collections:
                known_collections[name] = MilvusVectorStore(
                    uri=os.environ.get("MILVUS_URI"), token=os.environ.get("MILVUS_TOKEN"),
                    collection_name=name, embedding_service_url="https://aistudio.baidu.com/llm/lmapi/v3",
                    qianfan_api_key=os.environ.get("AISTUDIO_ACCESS_TOKEN")
                )
        return list(known_collections.keys())
    except:
        return list(known_collections.keys())

def split_text_into_chunks(text: str, chunk_size: int = 350, overlap: int = 100) -> list:
    """
    文本切分 (修复版)：强制切分超长行，防止 API 报错
    """
    if not text: return []
    
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    
    chunks = []
    current_chunk = []
    current_length = 0
    
    for line in lines:
        while len(line) > chunk_size:
            # 截取一段
            part = line[:chunk_size]
            # 剩下的放回去继续循环处理
            line = line[chunk_size:]
            
            if current_length + len(part) > chunk_size and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_length = 0
            
            current_chunk.append(part)
            current_length += len(part)
            
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_length = 0
        
        if current_length + len(line) > chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk))
        
            overlap_text = current_chunk[-1][-overlap:] if current_chunk else ""
            current_chunk = [overlap_text] if overlap_text else []
            current_length = len(overlap_text)
            
        current_chunk.append(line)
        current_length += len(line)
        
    # 处理最后的尾巴
    if current_chunk:
        content = "\n".join(current_chunk).strip()
        if content: chunks.append(content)
        
    return chunks
def process_uploaded_pdf(files, collection_name, ocr_lang_choice, progress=gr.Progress()):
    lang_code = "en" if "English" in ocr_lang_choice else "ch"
    if collection_name: collection_name = str(collection_name).strip()
    
    ready, msg = check_ready()
    if not ready: return msg
    if not files: return "⚠️ 请上传 PDF"
    
    if collection_name not in known_collections:
        create_collection_ui(collection_name)
    
    target_store = known_collections[collection_name]
    results = [] 
    col_img_dir = os.path.join(ASSET_DIR, collection_name)
    try: os.makedirs(col_img_dir, exist_ok=True)
    except: pass
    
    print(f"🔍 正在检查 {collection_name} 中的文档列表...")
    try:
        existing_files = set(target_store.list_documents())
    except Exception as e:
        print(f"⚠️ 获取文件列表失败: {e}")
        existing_files = set()

    print(f"\n[系统] 正在获取 PaddleX 引擎 (语言: {lang_code})...")
    engine = get_paddlex_pipeline(lang=lang_code)
    
    if engine is None:
        return "❌ 内部错误: AI 引擎加载失败，请检查控制台报错"

    for file_path in progress.tqdm(files, desc="PaddleX 批量解析中"):
        
       
        path_str = file_path.name if hasattr(file_path, 'name') else file_path
        filename = os.path.basename(path_str)
        abs_path = os.path.abspath(path_str)
    
        if filename in existing_files:
            log_msg = f"⏩ {filename} (已存在，跳过)"
            print(log_msg)
            results.append(log_msg) # 添加到UI日志
            time.sleep(0.05) # 给UI线程一点刷新时间
            continue
        
        file_img_dir = os.path.join(col_img_dir, os.path.splitext(filename)[0])
        if os.path.exists(file_img_dir): shutil.rmtree(file_img_dir)
        os.makedirs(file_img_dir, exist_ok=True)
        
        print(f"\n🚀 开始解析文件: {filename}")
        
        # 调用 PaddleX 预测
        try:
            prediction = engine.predict(
                input=abs_path, 
                device="cpu", 
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False
            )
            output = list(prediction)
        except Exception as e:
            err_msg = f"❌ {filename}: 引擎解析异常 ({str(e)})"
            print(err_msg)
            results.append(err_msg)
            continue

        file_chunk_count = 0 
        if output:
            for page_idx, res in enumerate(output):
                if not (hasattr(res, 'markdown') and res.markdown):
                    continue
                    
                md_data = res.markdown
                page_text = md_data.get('markdown_texts', '') 
                page_images = md_data.get('markdown_images', {})
             
                for img_path, img_val in page_images.items():
                    try:
                        sname = f"p{page_idx}_{int(time.time())}_{os.path.basename(img_path)}"
                        spath = os.path.join(file_img_dir, sname)
                        if isinstance(img_val, str):
                            with open(spath, "wb") as f: f.write(base64.b64decode(img_val))
                        elif hasattr(img_val, 'save'):
                            img_val.save(spath)
                        # 替换文本中的图片路径
                        page_text = page_text.replace(img_path, f"[图表: {sname}]")
                    except: pass
                
                if not page_text.strip(): continue

                page_chunks = split_text_into_chunks(page_text)
                
                docs = []
                for cid, chunk in enumerate(page_chunks):
                    docs.append({
                        "filename": filename, 
                        "page": page_idx,  # 写入真实页码
                        "content": f"文档: {filename} (P{page_idx+1})\n{chunk}", 
                        "chunk_id": file_chunk_count + cid
                    })
                
                if docs:
                    target_store.insert_documents(docs)
                    file_chunk_count += len(docs)
                    # print(f"  -> P{page_idx+1} 入库 {len(docs)} 条")

        if file_chunk_count > 0:
            success_msg = f"✅ {filename} (提取 {file_chunk_count} 片段)"
            results.append(success_msg)
        else:
            fail_msg = f"❌ {filename}: 未提取到有效内容"
            results.append(fail_msg)
            
        time.sleep(0.05)
            
    return "\n".join(results)

def ask_question_logic(question, collection_name, target_filename=None):
    ready, msg = check_ready()
    if not ready: return msg, "N/A"
    if not question.strip(): return "请输入问题", "0.0%"
    
    target_store = known_collections.get(collection_name, milvus_store)
    search_kwargs = {"top_k": 20}
    if target_filename and target_filename != "全部文档 (Global QA)":
        search_kwargs["expr"] = f"filename == '{target_filename}'"
        
    retrieved = target_store.search(question, **search_kwargs)
    if not retrieved: return "未找到相关内容。", "0.0%"
    
    processed, _ = reranker_filter.process(question, retrieved)
    final = processed[:5]
    top_score = final[0].get('composite_score', 0) if final else 0
    metric = f"{min(100, top_score/1.2):.1f}%"
    
    answer = ernie.answer_question(question, final)
    seen = set()
    sources = "\n\n📚 **参考来源:**\n"
    for c in final:
    
        page_num = c.get('page', 0) + 1
        fname = c.get('filename', '未知文档')

        key = f"{fname} (P{page_num})"
        
        if key not in seen:
            # 显示格式: - 文件名 (P页码) [Rel:分数]
            sources += f"- {key} [Rel:{c.get('composite_score',0):.0f}]\n"
            seen.add(key)
    return answer + sources, metric

def handle_image_upload(file, history):
    if not file: return history, ""
    history.append({"role": "user", "content": (file.name,)})
    try:
        engine = get_paddlex_pipeline()
        output = engine.predict(input=file.name)
        extracted_text = ""
        for res in output:
            if hasattr(res, 'markdown'): extracted_text += res.markdown.get('text', '') + "\n"

        if extracted_text:
            history.append({"role": "assistant", "content": f"✅ 内容:\n{extracted_text[:300]}..."})
        else:
            history.append({"role": "assistant", "content": "⚠️ 未识别到内容。"})
    except Exception as e:
        history.append({"role": "assistant", "content": f"❌ 失败: {e}"})
    return history, extracted_text

def chat_respond(message, history, collection_name, target_filename, img_context):
    if not message: return history, history, "", "N/A", img_context
    if not collection_name: 
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": "⚠️ 请先选择知识库"})
        return history, history, "", "N/A", img_context

    full_query = message
    if img_context: 
        full_query = f"{img_context}\n用户问题: {message}"
        img_context = "" 
    
    answer, metric = ask_question_logic(full_query, collection_name, target_filename)
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": answer})
    return history, history, "", metric, img_context

def analyze_doc_and_images(collection_name, filename):
    ready, msg = check_ready()
    if not ready: return "系统未连接", []
    if not filename or filename == "全部文档 (Global QA)": return "请选择具体文档...", []

    store = known_collections.get(collection_name, milvus_store)
    text = store.get_document_content(filename)
    
    if text:
        summary = ernie.generate_summary(text[:3000])
    else:
        summary = "无法获取内容 (可能是纯图片文档或解析失败)"
    
    images = []
    file_img_path = os.path.join(ASSET_DIR, collection_name, os.path.splitext(filename)[0])
    
    if os.path.exists(file_img_path):
        for img_file in sorted(os.listdir(file_img_path)):
            if img_file.lower().endswith(('.png', '.jpg', '.jpeg')):
                
                if "formula" in img_file.lower() or "img_in_for" in img_file.lower():
                    continue
              
                full_path = os.path.join(file_img_path, img_file)
               
                images.append((full_path, img_file))
                
    return f"📄 **{filename}**\n\n{summary}", images

def update_file_list(collection_name):
    ready, msg = check_ready()
    # 如果系统未就绪，返回空列表
    if not ready: return gr.update(choices=[], label="2. 文档 (未连接)")
    
    store = known_collections.get(collection_name, milvus_store)
    if not store: return gr.update(choices=[], label="2. 文档 (库不存在)")
    
    # 获取文件列表
    files = store.list_documents()
    count = len(files) # 统计数量
    
    choices = ["全部文档 (Global QA)"] + files
    # 在 label 中显示 (共 N 个)
    return gr.update(choices=choices, value=choices[0], label=f"2. 文档 (共 {count} 个)")

def update_file_list_for_delete(collection_name):
    ready, msg = check_ready()
    if not ready or not collection_name: 
        return gr.update(choices=[], label="选择要删除的文件")
        
    store = known_collections.get(collection_name, milvus_store)
    # 获取文件列表
    files = store.list_documents()
    count = len(files) # 统计数量
    return gr.update(choices=files, value=None, label=f"选择要删除的文件 (当前库共 {count} 个)")
def run_recall_test(collection_name):
    ready, msg = check_ready()
    if not ready: return msg
    if not collection_name: return "❌ 请先选择一个知识库"

    store = known_collections.get(collection_name, milvus_store)
    
    return store.test_self_recall(sample_size=20)
def create_collection_ui(new_name):
    ready, msg = check_ready()
    if not ready: return gr.update(), msg
    if not new_name: return gr.update(), "❌ 名称不能为空"
    try:
        new_store = MilvusVectorStore(
            uri=os.environ.get("MILVUS_URI"), token=os.environ.get("MILVUS_TOKEN"),
            collection_name=new_name, embedding_service_url="https://aistudio.baidu.com/llm/lmapi/v3",
            qianfan_api_key=os.environ.get("AISTUDIO_ACCESS_TOKEN")
        )
        dummy = [{"filename":"_init","page":0,"content":"init","chunk_id":0}]
        new_store.insert_documents(dummy)
        known_collections[new_name] = new_store
        updated = list(known_collections.keys())
        return gr.update(choices=updated, value=new_name), f"✅ 创建成功: {new_name}"
    except Exception as e:
        return gr.update(), f"❌ 创建失败: {e}"

def delete_collection_ui(name):
    ready, msg = check_ready()
    if not ready: return gr.update(), msg
    if not name: return gr.update(), "请选择"
    try:
        alias = "delete_conn"
        connections.connect(alias=alias, uri=os.environ.get("MILVUS_URI"), token=os.environ.get("MILVUS_TOKEN"))
        if utility.has_collection(name, using=alias): utility.drop_collection(name, using=alias)
        connections.disconnect(alias)
        if name in known_collections: del known_collections[name]
        img_path = os.path.join(ASSET_DIR, name)
        if os.path.exists(img_path): shutil.rmtree(img_path)
        updated = list(known_collections.keys())
        val = updated[0] if updated else None
        return gr.update(choices=updated, value=val), f"🗑️ 已删除: {name}"
    except Exception as e:
        return gr.update(), f"❌ 删除失败: {e}"

def delete_single_file(collection_name, filename):
    ready, msg = check_ready()
    if not ready: return msg
    if not collection_name: return "❌ 请先选择知识库"
    if not filename: return "❌ 请选择要删除的文件"
    
    store = known_collections.get(collection_name, milvus_store)
    msg = store.delete_document(filename)
    
    try:
        img_dir = os.path.join(ASSET_DIR, collection_name, os.path.splitext(filename)[0])
        if os.path.exists(img_dir):
            import shutil
            shutil.rmtree(img_dir)
            msg += " (关联图片已清理)"
    except: pass
    
    return msg

def refresh_all_dropdowns():
    if not system_ready: return gr.update(), gr.update(), gr.update()#, gr.update()
    new_cols = scan_remote_collections()
    # return (gr.update(choices=new_cols), gr.update(choices=new_cols), gr.update(choices=new_cols), gr.update(choices=new_cols))
    return (
        gr.update(choices=new_cols), 
        gr.update(choices=new_cols), 
        gr.update(choices=new_cols)
    )

custom_css = """
/* 1. 覆盖 Gradio 全局颜色变量 (保持全白风格) */
:root, body, .gradio-container {
    --body-background-fill: #ffffff !important;
    --background-fill-primary: #ffffff !important;
    --background-fill-secondary: #ffffff !important;
    --block-background-fill: #ffffff !important;
    --panel-background-fill: #ffffff !important;
    background-color: #ffffff !important;
}

/* 2. 强制容器背景为白色 */
.gr-group, .gr-box, .gr-panel, .gr-row, .gr-column, .gr-block {
    background-color: #ffffff !important;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

/* 3. 🟢 [核心修复] 排除 Checkbox 和 Radio，防止勾选状态看不见 */
textarea, select, .gr-input, .gr-form, .wrap, input:not([type="checkbox"]):not([type="radio"]) {
    background-color: #ffffff !important;
}

/* 4. 修复上传区域 */
.upload-container, .drop-zone {
    background-color: #ffffff !important;
}

/* 5. 顶部 Banner */
.header-banner {
    background: linear-gradient(135deg, #2563eb, #3b82f6);
    color: white;
    padding: 1.5rem;
    border-radius: 12px;
    margin-bottom: 15px;
}
.header-title { font-size: 1.5rem; font-weight: 700; }
.chatbot-container { min-height: 600px !important; }
"""
theme = gr.themes.Soft(primary_hue="blue", secondary_hue="slate")

with gr.Blocks(title="多文档智能分析与问答系统", theme=theme, css=custom_css) as demo:
    gr.HTML("""
        <div class="header-banner">
            <div class="header-title">🚀 多文档智能分析与问答系统 (PaddleOCR高精度版)</div>
            <div class="header-subtitle"> PaddleOCR  · ERNIE 4.5 · Milvus</div>
        </div>
    """)
    image_context_state = gr.State("")

    with gr.Tabs():
        with gr.TabItem("💡 智能问答"):
            with gr.Group():
                with gr.Row():
                    qa_col_select = gr.Dropdown(label="1. 知识库", choices=[], scale=3)
                    qa_file_select = gr.Dropdown(label="2. 文档", choices=["全部文档 (Global QA)"], value="全部文档 (Global QA)", scale=4)
                    refresh_btn = gr.Button("🔄 刷新", scale=1)
                
                with gr.Row():
                    with gr.Column(scale=6):
                        chatbot = gr.Chatbot(label="对话", height=650, show_label=False, elem_classes="chatbot-container", type='messages')
                        with gr.Row():
                            # upload_img_btn = gr.UploadButton("📷", file_types=["image"], scale=1, size="sm")
                            msg = gr.Textbox(show_label=False, placeholder="输入问题...", scale=10, autofocus=True)
                            submit_btn = gr.Button("发送", variant="primary", scale=1)
                        with gr.Row():
                            qa_metric = gr.Label(label="置信度", value="N/A", scale=1)
                            clear_btn = gr.ClearButton([msg, chatbot, image_context_state], value="🧹", size="sm", scale=1)

                    with gr.Column(scale=4):
                        doc_summary = gr.Markdown(value="👈 请选择文档...", elem_classes="gr-box")
                        doc_gallery = gr.Gallery(label="PaddleX 提取图表", show_label=False, height=400, object_fit="contain")

            refresh_btn.click(update_file_list, inputs=[qa_col_select], outputs=[qa_file_select])
            qa_col_select.change(update_file_list, inputs=[qa_col_select], outputs=[qa_file_select])
            qa_file_select.change(analyze_doc_and_images, inputs=[qa_col_select, qa_file_select], outputs=[doc_summary, doc_gallery])
            
            # upload_img_btn.upload(handle_image_upload, inputs=[upload_img_btn, chatbot], outputs=[chatbot, image_context_state])
            msg.submit(chat_respond, inputs=[msg, chatbot, qa_col_select, qa_file_select, image_context_state], outputs=[chatbot, chatbot, msg, qa_metric, image_context_state])
            submit_btn.click(chat_respond, inputs=[msg, chatbot, qa_col_select, qa_file_select, image_context_state], outputs=[chatbot, chatbot, msg, qa_metric, image_context_state])

        with gr.TabItem("🛠️ 知识库管理"):
            with gr.Row():
                with gr.Column(scale=1):
                    # 模块: 上传文档
                    with gr.Group():
                        gr.Markdown("### 📤 上传文档")
                        # 这个下拉框同时控制上传和测试
                        upload_col_select = gr.Dropdown(label="目标 Collection", allow_custom_value=True, choices=[])
                        # OCR 语言选择
                        ocr_lang_select = gr.Radio(
                            choices=["中英文通用 (默认)", "纯英文 (English)"], 
                            value="中英文通用 (默认)", 
                            label="OCR 模型语言 (纯英文文档建议切换)"
                        )
                        # ============================
                        files_input = gr.File(label="PDF文件", file_count="multiple", type="filepath")
                        upload_btn = gr.Button("PaddleX 智能解析 (V3)", variant="primary")
                        stop_btn = gr.Button("🛑 终止", variant="stop", scale=1)
                        upload_log = gr.Textbox(label="日志", lines=4)
                    
                    # 模块: 索引测试
                    with gr.Group():
                        gr.Markdown("### 🧪 索引质量自测 (FLAT)")
                        with gr.Row():
                            test_recall_btn = gr.Button("🚀 运行召回测试", variant="secondary", scale=3)
                        # 结果显示框
                        test_result_box = gr.Textbox(show_label=False, lines=2)

                with gr.Column(scale=1):
                    with gr.Group():
                        gr.Markdown("### ⚙️ 库管理操作")
                        
                        gr.Markdown("#### 🆕 新建知识库")
                        with gr.Row():
                            new_col_name = gr.Textbox(show_label=False, scale=3)
                            create_btn = gr.Button("创建", variant="secondary", scale=1)
                        create_msg = gr.Label(show_label=False)
                        
                        gr.Markdown("---")
                        gr.Markdown("#### 📄 删除指定文档")
                        with gr.Row():
                            # 下拉框：选择要删除的文件
                            del_file_select = gr.Dropdown(show_label=False, choices=[], scale=3, allow_custom_value=True)
                            btn_del_file = gr.Button("删除文件", variant="stop", scale=1)
                        del_file_msg = gr.Textbox(show_label=False, lines=1, interactive=False)

                        gr.Markdown("---")
                        gr.Markdown("#### 🗑️ 删除知识库")
                        with gr.Row():
                            del_col_select = gr.Dropdown(show_label=False, choices=[], scale=3)
                            del_btn = gr.Button("删除", variant="stop", scale=1)

            # === 🔽 事件绑定区域 ===
            # 1. 上传
            upload_event = upload_btn.click(process_uploaded_pdf, inputs=[files_input, upload_col_select, ocr_lang_select], outputs=[upload_log])
            stop_btn.click(fn=lambda: None, inputs=None, outputs=None, cancels=[upload_event])
            # 2. 刷新
            upload_event.then(refresh_all_dropdowns, outputs=[qa_col_select, upload_col_select, del_col_select])\
                        .then(update_file_list, inputs=[qa_col_select], outputs=[qa_file_select])
            # 3. 创建
            create_btn.click(create_collection_ui, inputs=[new_col_name], outputs=[upload_col_select, create_msg])\
                      .then(refresh_all_dropdowns, outputs=[qa_col_select, upload_col_select, del_col_select])
            # 4. 删除
            # del_btn.click(delete_collection_ui, inputs=[del_col_select], outputs=[upload_col_select, create_msg])\
            #        .then(refresh_all_dropdowns, outputs=[qa_col_select, upload_col_select, del_col_select])
            btn_del_file.click(
                fn=delete_single_file,                  # 1. 执行删除逻辑
                inputs=[upload_col_select, del_file_select], # 传入：当前选中的库名、要删除的文件名
                outputs=[del_file_msg]                  # 输出：提示信息
            ).then(
                fn=update_file_list_for_delete,         # 2. 删除成功后，自动刷新列表
                inputs=[upload_col_select],             # 传入：当前库名
                outputs=[del_file_select]               # 输出：更新下拉框（把已删除的文件移除）
            )
            upload_col_select.change(
                update_file_list_for_delete,   # 调用刚才修改过的函数
                inputs=[upload_col_select],    # 输入：当前选中的知识库
                outputs=[del_file_select]      # 输出：更新删除文件的下拉框（含数量标题）
            )
            # 5. 召回率测试
            test_recall_btn.click(
                run_recall_test, 
                inputs=[upload_col_select], 
                outputs=[test_result_box]
            )

        # with gr.TabItem("⚙️ 系统配置"):
        #     with gr.Group():
        #         tk_aistudio = gr.Textbox(label="AISTUDIO_ACCESS_TOKEN", type="password", value=os.getenv("AISTUDIO_ACCESS_TOKEN", ""))
        #         tk_qianfan = gr.Textbox(label="QIANFAN_API_KEY", type="password", value=os.getenv("QIANFAN_API_KEY", ""))
        #         tk_uri = gr.Textbox(label="MILVUS_URI", value=os.getenv("MILVUS_URI", ""))
        #         tk_token = gr.Textbox(label="MILVUS_TOKEN", type="password", value=os.getenv("MILVUS_TOKEN", ""))
        #         btn_connect = gr.Button("连接", variant="primary")
        #         connect_log = gr.Textbox(label="状态", interactive=False)
        #         btn_connect.click(initialize_system, inputs=[tk_aistudio, tk_qianfan, tk_uri, tk_token], outputs=[connect_log, qa_col_select, upload_col_select, del_col_select])
        with gr.TabItem("⚙️ 系统配置"):
            with gr.Group():
                gr.Markdown("### 🔌 连接设置")
                
                # === 1. 增加本地模式开关 ===
                use_local_mode = gr.Checkbox(
                    label="📂 启用本地离线模式 (Milvus Lite)", 
                    value=False,
                    info="勾选后，数据将保存在本地 .db 文件中，无需 Milvus 服务器。"
                )
                
                # === 2. 输入框区域 ===
                with gr.Row():
                    # API Key 始终需要 (用于 PaddleX 和 Embedding)
                    tk_aistudio = gr.Textbox(label="AISTUDIO_ACCESS_TOKEN", type="password", value=os.getenv("AISTUDIO_ACCESS_TOKEN", ""), scale=1)
                    tk_qianfan = gr.Textbox(label="QIANFAN_API_KEY", type="password", value=os.getenv("QIANFAN_API_KEY", ""), scale=1)
                
                with gr.Row():
                    # URI 和 Token 会根据上面的开关变化
                    tk_uri = gr.Textbox(label="MILVUS_URI", value=os.getenv("MILVUS_URI", ""), placeholder="例如: http://localhost:19530", scale=1)
                    tk_token = gr.Textbox(label="MILVUS_TOKEN", type="password", value=os.getenv("MILVUS_TOKEN", ""), scale=1)
                
                btn_connect = gr.Button("连接 / 初始化系统", variant="primary")
                connect_log = gr.Textbox(label="系统状态", interactive=False, lines=2)

                # === 3. 交互逻辑：切换模式 ===
                def toggle_mode(is_local):
                    if is_local:
                        # 切换到本地模式：填入本地文件名，清空并禁用 Token
                        return (
                            gr.update(value="./my_knowledge_base.db", interactive=False, label="本地数据库路径"), 
                            gr.update(value="", interactive=False, placeholder="本地模式无需 Token")
                        )
                    else:
                        # 切换回服务器模式：恢复默认值，启用输入
                        return (
                            gr.update(value=os.getenv("MILVUS_URI", ""), interactive=True, label="MILVUS_URI"), 
                            gr.update(value=os.getenv("MILVUS_TOKEN", ""), interactive=True, placeholder="")
                        )

                use_local_mode.change(toggle_mode, inputs=[use_local_mode], outputs=[tk_uri, tk_token])

                # === 4. 连接按钮 (保持原逻辑，只需减少 outputs 数量以修复之前的警告) ===
                btn_connect.click(
                    initialize_system, 
                    inputs=[tk_aistudio, tk_qianfan, tk_uri, tk_token], 
                    # 注意：这里只保留了 4 个 output，修复了之前的警告
                    outputs=[connect_log, qa_col_select, upload_col_select, del_col_select]
                )
def find_free_port(start=7860):
    for port in range(start, start+10):
        try:
            s = socket.socket()
            s.bind(('', port))
            s.close()
            return port
        except OSError: continue
    return start

if __name__ == "__main__":
    port = find_free_port()
    print(f"🚀 启动 UI: http://127.0.0.1:{port}")
    demo.launch(server_name="127.0.0.1", server_port=port, inbrowser=True)