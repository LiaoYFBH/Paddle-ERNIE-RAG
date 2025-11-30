import os
import sys
import logging
import shutil
import base64
import time
import requests
import json
import re
import binascii
from dotenv import load_dotenv

# 引入工具类
try:
    from utils.vector_store import MilvusVectorStore
    from utils.ernie_client import ERNIEClient
    from utils.reranker_v2 import RerankerAndFilterV2
except ImportError as e:
    print(f"❌ 导入工具类失败: {e}")
    # 为了防止报错导致程序崩溃，这里可以做个软处理或直接退出
    # exit(1) 

from pymilvus import utility, connections
import gradio as gr

load_dotenv()
def on_gallery_select(evt: gr.SelectData, collection_name, doc_filename):
    """
    用户点击图片时，解析出：路径、文档名、页码
    """
    if not collection_name or not doc_filename:
        return None, "⚠️ 请先选择文档"
    
    try:
        # 1. 定位图片目录
        file_img_path = os.path.join(ASSET_DIR, collection_name, os.path.splitext(doc_filename)[0])
        valid_images = []
        if os.path.exists(file_img_path):
            # 必须与 analyze_doc_and_images 排序一致
            for img_file in sorted(os.listdir(file_img_path)):
                if img_file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    if "formula" in img_file.lower() or "img_in_for" in img_file.lower():
                        continue
                    full_path = os.path.join(file_img_path, img_file)
                    valid_images.append(full_path)
        
        # 2. 获取选中的图片路径
        if 0 <= evt.index < len(valid_images):
            selected_img_path = valid_images[evt.index]
            filename_only = os.path.basename(selected_img_path)
            
            # 3. 🟢 核心：从文件名解析页码 (格式: p0_123456_name.jpg)
            # p(\d+) 匹配 p0, p1, p10...
            page_match = re.match(r"p(\d+)_", filename_only)
            page_num = int(page_match.group(1)) + 1 if page_match else "未知"
            
            print(f"🖼️ 选中图片: {filename_only} (第 {page_num} 页)")
            
            # 4. 构造完整上下文包 (Dict) 而不是简单的 String
            img_context_data = {
                "path": selected_img_path,
                "doc_name": doc_filename,
                "page": page_num,
                "collection": collection_name
            }
            
            return img_context_data, f"✅ 已选中第 {page_num} 页的图表，可询问详情！"
        
        return None, "❌ 无法定位图片"
    except Exception as e:
        print(f"❌ 图片选择异常: {e}")
        return None, f"选择出错: {e}"
def encode_name(ui_name):
    """把中文名称转为 Milvus 合法的 Hex 字符串 (例如: '测试' -> 'kb_e6b58b...')"""
    if not ui_name: return ""
    # 如果本身就是纯英文/数字/下划线，且符合规范，直接返回 (兼容旧库)
    if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', ui_name):
        return ui_name
    
    # 否则进行 Hex 编码，并加前缀 kb_ 保证字母开头
    hex_str = binascii.hexlify(ui_name.encode('utf-8')).decode('utf-8')
    return f"kb_{hex_str}"

def decode_name(real_name):
    """把 Hex 字符串转回中文"""
    if not real_name: return ""
    if real_name.startswith("kb_"):
        try:
            # 去掉前缀，尝试反解
            hex_str = real_name[3:]
            return binascii.unhexlify(hex_str).decode('utf-8')
        except:
            # 解码失败（可能是用户自己手动建的以 kb_ 开头的英文库），返回原名
            return real_name
    return real_name
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 屏蔽无关日志
silence_libs = ["httpx", "httpcore", "urllib3"]
for lib in silence_libs:
    logging.getLogger(lib).setLevel(logging.ERROR)

# 目录准备
ASSET_DIR = "assets"
os.makedirs(ASSET_DIR, exist_ok=True)

# === 全局状态变量 ===
ernie = None
milvus_store = None
reranker_filter = None
known_collections = {}
system_ready = False

# === 核心类: 在线 PDF 解析器 ===
class OnlinePDFParser:
    """处理云端 API 调用"""
    def __init__(self, api_url, token):
        self.api_url = api_url
        self.token = token

    def predict(self, file_path):
        if not self.token:
            return None, "❌ 错误: 未配置 Token"
        if not self.api_url:
            return None, "❌ 错误: 未配置 API URL"
        
        file_name = os.path.basename(file_path)
        print(f"☁️ [Online] 正在请求在线 OCR API: {file_name}")
        
        try:
            with open(file_path, "rb") as file:
                file_bytes = file.read()
                file_data = base64.b64encode(file_bytes).decode("ascii")

            # 简单判断文件类型
            ext = os.path.splitext(file_name)[1].lower()
            file_type = 0 if ext == '.pdf' else 1 
            
            payload = {
                "file": file_data,
                "fileType": file_type,
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useTextlineOrientation": False,
                "useChartRecognition": False,
            }
            
            headers = {
                "Authorization": f"token {self.token}", 
                "Content-Type": "application/json"
            }
            
            # 大文件上传需要较长时间，超时设为 600秒
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=600)
            
            if response.status_code != 200:
                print(f"❌ [API Error] HTTP {response.status_code}: {response.text[:100]}")
                return None, f"API HTTP错误 ({response.status_code})"
            
            res_json = response.json()
            
            if "errorCode" in res_json and res_json["errorCode"]:
                err_msg = res_json.get('errorMsg', '未知错误')
                print(f"❌ [API Error] 业务错误: {err_msg}")
                return None, f"API 业务错误: {err_msg}"

            api_result = res_json.get("result", {})
            parsing_results = api_result.get("layoutParsingResults", [])
            
            if not parsing_results:
                if isinstance(api_result, list):
                     return None, "⚠️ 检测到纯 OCR 接口返回，本系统需要 Layout Parsing 结构。"
                print(f"⚠️ [API Warning] layoutParsingResults 为空。Keys: {list(res_json.keys())}")
                return None, "API 返回结果为空 (可能文件无法解析)"

            class MockResult:
                def __init__(self, md_text, imgs):
                    self.markdown = {
                        'markdown_texts': md_text,
                        'markdown_images': imgs
                    }

            mock_outputs = []
            
            for i, item in enumerate(parsing_results):
                md_data = item.get("markdown", {})
                raw_text = md_data.get("text", "")
                
                # 处理图片下载
                image_urls = md_data.get("images", {})
                processed_images = {}
                
                if image_urls:
                    print(f"   ↳ 正在下载第 {i+1} 部分的 {len(image_urls)} 张图片...")
                    for img_key, img_url in image_urls.items():
                        try:
                            img_resp = requests.get(img_url, timeout=30)
                            if img_resp.status_code == 200:
                                b64_str = base64.b64encode(img_resp.content).decode('utf-8')
                                processed_images[img_key] = b64_str
                        except Exception as e: pass
                
                mock_outputs.append(MockResult(raw_text, processed_images))
            
            return mock_outputs, "Success"

        except Exception as e:
            return None, f"请求异常: {str(e)}"

# === 文本处理工具 ===
def split_text_into_chunks(text: str, chunk_size: int = 300, overlap: int = 120) -> list:
    if not text: return []
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    chunks = []
    current_chunk = []
    current_length = 0
    for line in lines:
        while len(line) > chunk_size:
            part = line[:chunk_size]
            line = line[chunk_size:]
            if current_length + len(part) > chunk_size and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_length = 0
            current_chunk.append(part)
            current_length += len(part)
        if current_length + len(line) > chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk))
            overlap_text = current_chunk[-1][-overlap:] if current_chunk else ""
            current_chunk = [overlap_text] if overlap_text else []
            current_length = len(overlap_text)
        current_chunk.append(line)
        current_length += len(line)
    if current_chunk:
        content = "\n".join(current_chunk).strip()
        if content: chunks.append(content)
    return chunks

def check_ready():
    if not system_ready: return False, "⚠️ 系统未连接"
    return True, ""

def scan_remote_collections():
    global known_collections, ernie
    try:
        alias = f"scan_{int(time.time())}"
        connections.connect(alias=alias, uri=os.environ.get("MILVUS_URI"), token=os.environ.get("MILVUS_TOKEN"))
        all_colls = utility.list_collections(using=alias)
        connections.disconnect(alias)
        for real_name in all_colls:
            # 🟢 解码：获取 UI 显示用的名字
            ui_name = decode_name(real_name)
            
            if ui_name not in known_collections:
                # 🟢 关键：字典 Key 用中文(ui_name)，但传给 Milvus 的参数用真名(real_name)
                known_collections[ui_name] = MilvusVectorStore(
                    uri=os.environ.get("MILVUS_URI"), 
                    token=os.environ.get("MILVUS_TOKEN"),
                    collection_name=real_name,  # <--- 这里必须是 encoded 的真名
                    embedding_client=ernie
                )
        # for name in all_colls:
            # if name not in known_collections:
                # 传入全局配置的 ernie 客户端
                # known_collections[name] = MilvusVectorStore(
                #     uri=os.environ.get("MILVUS_URI"), token=os.environ.get("MILVUS_TOKEN"),
                #     collection_name=name, embedding_client=ernie
                # )
        return list(known_collections.keys())
    except:
        return list(known_collections.keys())

def initialize_system(
    llm_api_base, llm_api_key, llm_model,
    embed_api_base, embed_api_key, embed_model,
    ocr_url, ocr_token,
    milvus_uri, milvus_token,
    api_qps 
):
    global ernie, milvus_store, reranker_filter, system_ready, known_collections

    # 1. 基础清理
    milvus_uri = milvus_uri.strip() if milvus_uri else ""
    milvus_token = milvus_token.strip() if milvus_token else ""

    is_local_mode = milvus_uri.endswith(".db")
    # 检查基本必要参数 (LLM Key, Embed Key, Milvus URI)
    basic_check = all([llm_api_key, embed_api_key, milvus_uri])
    token_check = True if is_local_mode else bool(milvus_token)

    if not (basic_check and token_check):
        return "❌ 请填写必要信息 (LLM Key, Embed Key, Milvus URI)", gr.update(), gr.update(), gr.update()

    try:
        # 2. 设置环境变量 (供其他模块或持久化使用)
        os.environ["MILVUS_URI"] = milvus_uri
        if milvus_token: os.environ["MILVUS_TOKEN"] = milvus_token
        
        # 存储 OCR 配置到 Env，以便上传时使用
        if ocr_url: os.environ["OCR_API_URL"] = ocr_url
        if ocr_token: os.environ["OCR_ACCESS_TOKEN"] = ocr_token

        # 3. Milvus 重连清理
        try:
            if connections.has_connection("default"):
                connections.disconnect("default")
        except: pass

        known_collections = {}
        
        # 4. 初始化 ERNIE Client (传入 QPS)
        ernie = ERNIEClient(
            llm_api_base=llm_api_base,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            embed_api_base=embed_api_base,
            embed_api_key=embed_api_key,
            embed_model=embed_model,
            qps=api_qps
        )
        
        reranker_filter = RerankerAndFilterV2()

        # 5. 初始化 Milvus Store (传入配置好的 ernie client)
        # milvus_store = MilvusVectorStore(
        #     uri=milvus_uri,
        #     token=milvus_token, 
        #     collection_name="默认知识库", 
        #     embedding_client=ernie 
        # )
        
        # known_collections = {milvus_store.collection_name: milvus_store}
        default_ui_name = "默认知识库"
        default_real_name = encode_name(default_ui_name)

        milvus_store = MilvusVectorStore(
            uri=milvus_uri,
            token=milvus_token, 
            collection_name=default_real_name, # 使用编码后的名字
            embedding_client=ernie 
        )
        
        # 存入字典
        known_collections = {default_ui_name: milvus_store}
        try: scan_remote_collections()
        except: pass
        
        cols = list(known_collections.keys())
        default_col = cols[0] if cols else None
        
        system_ready = True
        return (
            f"✅ 连接成功 (QPS: {api_qps})", 
            gr.update(choices=cols, value=default_col),
            gr.update(choices=cols, value=default_col),
            gr.update(choices=cols, value=default_col)
        )
    except Exception as e:
        return f"❌ 失败: {str(e)}", gr.update(), gr.update(), gr.update()

def process_uploaded_pdf(files, collection_name, progress=gr.Progress()):
    if collection_name: collection_name = str(collection_name).strip()
    
    # 初始化日志缓冲区
    log_buffer = "🚀 任务启动...\n"
    yield log_buffer # 立即推送第一条
    
    ready, msg = check_ready()
    if not ready: 
        log_buffer += f"\n{msg}"
        yield log_buffer
        return
        
    if not files: 
        log_buffer += "\n⚠️ 未检测到文件，请上传 PDF。"
        yield log_buffer
        return
    
    if collection_name not in known_collections:
        create_collection_ui(collection_name)
    
    target_store = known_collections[collection_name]
    col_img_dir = os.path.join(ASSET_DIR, collection_name)
    try: os.makedirs(col_img_dir, exist_ok=True)
    except: pass
    
    # 读取配置
    token = os.environ.get("OCR_ACCESS_TOKEN", os.environ.get("AISTUDIO_ACCESS_TOKEN"))
    api_url = os.environ.get("OCR_API_URL")
    
    if not api_url or not token:
        log_buffer += "\n❌ 错误: OCR 配置缺失，请检查系统配置。"
        yield log_buffer
        return

    online_parser = OnlinePDFParser(api_url, token)
    try: existing_files = set(target_store.list_documents())
    except: existing_files = set()

    total_files = len(files)
    
    for i, file_path in enumerate(files):
        # 1. 准备阶段
        path_str = file_path.name if hasattr(file_path, 'name') else file_path
        filename = os.path.basename(path_str)
        abs_path = os.path.abspath(path_str)
        
        base_prog = i / total_files
        
        # === 实时日志更新 ===
        log_buffer += f"\n--------------------------------------------------\n"
        log_buffer += f"📄 [{i+1}/{total_files}] 正在处理: {filename}\n"
        yield log_buffer # 推送日志

        if filename in existing_files:
            log_buffer += f"⏩ 文件已存在，跳过。\n"
            progress((i + 1) / total_files, desc=f"跳过: {filename}")
            yield log_buffer
            continue
            
        file_img_dir = os.path.join(col_img_dir, os.path.splitext(filename)[0])
        if os.path.exists(file_img_dir): shutil.rmtree(file_img_dir)
        os.makedirs(file_img_dir, exist_ok=True)
        
        # 2. 云端 OCR 请求阶段
        progress(base_prog + 0.05, desc=f"☁️ OCR请求中: {filename}")
        log_buffer += f"☁️ 正在请求在线 OCR 服务 (大文件可能需耗时)...\n"
        yield log_buffer
        
        output = []
        try:
            output, err_msg = online_parser.predict(abs_path)
            if output is None:
                log_buffer += f"❌ OCR 失败: {err_msg}\n"
                yield log_buffer
                continue
            log_buffer += f"✅ OCR 解析成功，开始处理内容...\n"
            yield log_buffer
        except Exception as e:
            log_buffer += f"❌ 异常: {str(e)}\n"
            yield log_buffer
            continue

        # 3. 入库阶段
        file_chunk_count = 0 
        if output:
            total_pages = len(output)
            for page_idx, res in enumerate(output):
                # 更新进度条
                step_prog = (page_idx / total_pages) * 0.8
                current_total = base_prog + 0.2 + (step_prog / total_files)
                progress(current_total, desc=f"📥 入库中: {filename} (P{page_idx+1})")
                
                # 只有当页码变化时才推送日志，避免太频繁刷屏
                if page_idx % 5 == 0: 
                    log_buffer += f"   ↳ 正在处理第 {page_idx+1}/{total_pages} 页...\n"
                    yield log_buffer

                md_data = res.markdown
                page_text = md_data.get('markdown_texts', '') 
                page_images = md_data.get('markdown_images', {})
             
                # 图片保存逻辑...
                for img_path_key, img_val in page_images.items():
                    try:
                        base_name = os.path.basename(img_path_key)
                        sname = f"p{page_idx}_{int(time.time())}_{base_name}"
                        if not sname.endswith(('.jpg', '.png')): sname += ".jpg"
                        spath = os.path.join(file_img_dir, sname)

                        if isinstance(img_val, str):
                            with open(spath, "wb") as f: f.write(base64.b64decode(img_val))
                        elif hasattr(img_val, 'save'):
                            img_val.save(spath)
                        
                        page_text = page_text.replace(img_path_key, f"[图表: {sname}]")
                    except Exception as e: pass
                
                if not page_text.strip(): continue

                page_chunks = split_text_into_chunks(page_text)
                
                # 构造 Doc
                docs = []
                for cid, chunk in enumerate(page_chunks):
                    header = f"文档: {filename} (P{page_idx+1})\n"
                    safe_limit = 380 - len(header)
                    safe_chunk = chunk if len(chunk) <= safe_limit else chunk[:safe_limit] + "..."
                    docs.append({
                        "filename": filename, 
                        "page": page_idx, 
                        "content": f"{header}{safe_chunk}", 
                        "chunk_id": file_chunk_count + cid
                    })
                
                if docs:
                    target_store.insert_documents(docs)
                    file_chunk_count += len(docs)

        if file_chunk_count > 0:
            log_buffer += f"✅ {filename}: 成功入库 {file_chunk_count} 个片段。\n"
        else:
            log_buffer += f"⚠️ {filename}: 未提取到有效内容。\n"
        
        yield log_buffer # 更新单个文件完成后的状态
            
    log_buffer += "\n✨ 所有任务已完成！"
    yield log_buffer

def ask_question_logic(question, collection_name, target_filename=None):
    ready, msg = check_ready()
    if not ready: return msg, "N/A"
    if not question.strip(): return "请输入问题", "0.0%"
    
    # 双向翻译逻辑
    expanded_query = question
    try:
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in question)
        prompt = f"Translate the following Chinese query into English directly without explanation:\n{question}" if has_chinese else f"将以下英文问题直接翻译成中文，不要解释：\n{question}"
        
        if ernie:
            translated_part = ernie.chat([{"role": "user", "content": prompt}])
            if translated_part:
                expanded_query = f"{question} {translated_part}"
                print(f"✅ [Query] 双语增强后: {expanded_query}")
    except Exception as e: pass

    target_store = known_collections.get(collection_name, milvus_store)
    search_kwargs = {"top_k": 60}
    if target_filename and target_filename != "全部文档 (Global QA)":
        search_kwargs["expr"] = f"filename == '{target_filename}'"
        
    retrieved = target_store.search(expanded_query, **search_kwargs)
    if not retrieved: return "未找到相关内容。", "0.0%"
    
    processed, _ = reranker_filter.process(expanded_query, retrieved)
    final = processed[:22]
    top_score = final[0].get('composite_score', 0) if final else 0
    metric = f"{min(100, top_score):.1f}%"
    
    answer = ernie.answer_question(question, final)
    seen = set()
    sources = "\n\n📚 **参考来源:**\n"
    for c in final:
        page_num = c.get('page', 0) + 1
        fname = c.get('filename', '未知文档')
        key = f"{fname} (P{page_num})"
        if key not in seen:
            sources += f"- {key} [相关性:{c.get('composite_score',0):.0f}%]\n"
            seen.add(key)
            
    return answer + sources, metric
def chat_respond(message, history, collection_name, target_filename, img_context_data):
    if not message: return history, history, "", "N/A", img_context_data
    
    # === 变量初始化 ===
    # 我们先准备好默认的“用户提问”和“机器回答”变量
    # 无论走哪条路，最后都只把这两个变量加进 history
    user_display_text = message
    bot_response_text = ""
    metric_info = "N/A"
    
    # 状态标记
    vision_success = False
    
    # ============================================================
    # 1️⃣ 尝试多模态 (Vision) 通道
    # ============================================================
    if img_context_data and isinstance(img_context_data, dict) and os.path.exists(img_context_data.get("path", "")):
        img_path = img_context_data["path"]
        page_num = img_context_data["page"]
        doc_name = img_context_data["doc_name"]
        col_name = img_context_data.get("collection")
        
        # 1.1 准备背景文本
        page_text_context = ""
        try:
            store = known_collections.get(col_name, milvus_store)
            db_page_idx = int(page_num) - 1 if isinstance(page_num, int) else 0
            res = store.collection.query(
                expr=f'filename == "{doc_name}" and page == {db_page_idx}',
                output_fields=["content"], limit=3
            )
            texts = [r['content'] for r in res]
            if texts: page_text_context = "\n".join(texts)[:800]
        except: pass

        # 1.2 构造 Prompt (如果降级，这也将作为 RAG 的输入)
        final_prompt = f"""
        【任务】结合图片和背景信息回答问题。
        【图片元数据】来源：{doc_name} (P{page_num})
        【背景文本】{page_text_context}
        【用户问题】{message}
        """

        # 1.3 请求模型
        try:
            print(f"📷 正在请求多模态模型...")
            answer = ernie.chat_with_image(final_prompt, img_path)
            
            # 只有当回答有效，且不包含错误提示时，才算成功
            if answer and "失败" not in answer:
                # ✅ 成功！更新暂存变量
                user_display_text = f"[针对 P{page_num} 图表] {message}"
                # 1. 构造来源信息 (保持与文本 RAG 格式一致)
                vision_source = f"\n\n📚 **参考来源:**\n- 🖼️ {doc_name} (P{page_num}) [视觉锁定]"
                
                # 2. 拼接回答
                bot_response_text = answer + vision_source
                metric_info = "Vision Mode"
                vision_success = True 
                
        except Exception as e:
            err_str = str(e).lower()
            if "400" in err_str or "invalid" in err_str or "support" in err_str:
                print(f"⚠️ 模型不支持图片，准备切换至文本模式。")
            else:
                print(f"❌ 多模态调用异常: {e}")

    # ============================================================
    # 2️⃣ 降级/常规 RAG 通道 (仅当多模态未成功时执行)
    # ============================================================
    if not vision_success:
        print("🔄 执行文本 RAG 通道")
        
        if not collection_name: 
            bot_response_text = "⚠️ 请先选择知识库"
        else:
            # 构造查询
            full_query = message
            prefix_hint = ""
            
            # 如果之前准备过 final_prompt（说明是降级下来的），我们复用它作为文本输入
            if 'final_prompt' in locals() and final_prompt:
                full_query = final_prompt
                prefix_hint = "ℹ️ **系统提示**：当前模型不支持视觉输入，已自动根据图表周围的文本为您分析。\n\n"

            # 执行检索问答
            answer, metric = ask_question_logic(full_query, collection_name, target_filename)
            
            # 更新暂存变量
            bot_response_text = prefix_hint + answer
            metric_info = metric

    # ============================================================
    # 3️⃣ 统一出口 (Single Exit) - 绝对防止双重气泡
    # ============================================================
    history.append({"role": "user", "content": user_display_text})
    history.append({"role": "assistant", "content": bot_response_text})
    
    # 如果多模态成功，我们要清空 img_context_data (返回 None)
    # 如果失败/降级，我们也清空它（假设用户的一问一答消耗了这次图片选择），或者你可以保留
    # 这里我们选择消耗掉，避免状态混乱
    return history, "", metric_info, None
# def chat_respond(message, history, collection_name, target_filename, img_context):
#     if not message: return history, history, "", "N/A", img_context
#     if not collection_name: 
#         history.append({"role": "user", "content": message})
#         history.append({"role": "assistant", "content": "⚠️ 请先选择知识库"})
#         return history, history, "", "N/A", img_context

#     full_query = message
#     if img_context: 
#         full_query = f"{img_context}\n用户问题: {message}"
#         img_context = "" 
    
#     answer, metric = ask_question_logic(full_query, collection_name, target_filename)
#     history.append({"role": "user", "content": message})
#     history.append({"role": "assistant", "content": answer})
#     return history, history, "", metric, img_context

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
    if not ready: return gr.update(choices=[], label="2. 文档 (未连接)")
    
    store = known_collections.get(collection_name, milvus_store)
    if not store: return gr.update(choices=[], label="2. 文档 (库不存在)")
    
    files = store.list_documents()
    count = len(files)
    choices = ["全部文档 (Global QA)"] + files
    return gr.update(choices=choices, value=choices[0], label=f"2. 文档 (共 {count} 个)")

def update_file_list_for_delete(collection_name):
    ready, msg = check_ready()
    if not ready or not collection_name: 
        return gr.update(choices=[], label="选择要删除的文件")
        
    store = known_collections.get(collection_name, milvus_store)
    files = store.list_documents()
    count = len(files)
    return gr.update(choices=files, value=None, label=f"选择要删除的文件 (当前库共 {count} 个)")

def run_recall_test(collection_name):
    ready, msg = check_ready()
    if not ready: return msg
    if not collection_name: return "❌ 请先选择一个知识库"

    store = known_collections.get(collection_name, milvus_store)
    return store.test_self_recall(sample_size=20)

def create_collection_ui(new_name):
    global ernie
    ready, msg = check_ready()
    if not ready: return gr.update(), msg
    if not new_name: return gr.update(), "❌ 名称不能为空"
    # try:
    #     # 传入全局配置的 ernie
    #     new_store = MilvusVectorStore(
    #         uri=os.environ.get("MILVUS_URI"), token=os.environ.get("MILVUS_TOKEN"),
    #         collection_name=new_name, embedding_client=ernie
    #     )
    #     dummy = [{"filename":"_init","page":0,"content":"init","chunk_id":0}]
    #     new_store.insert_documents(dummy)
    #     known_collections[new_name] = new_store
    #     updated = list(known_collections.keys())
    #     return gr.update(choices=updated, value=new_name), f"✅ 创建成功: {new_name}"
    real_milvus_name = encode_name(new_name)
    
    try:
        # 🟢 传给 Milvus 的是编码后的名字
        new_store = MilvusVectorStore(
            uri=os.environ.get("MILVUS_URI"), 
            token=os.environ.get("MILVUS_TOKEN"),
            collection_name=real_milvus_name, # <--- 真实表名
            embedding_client=ernie
        )
        # # 初始化一下
        # dummy = [{"filename":"_init","page":0,"content":"init","chunk_id":0}]
        # new_store.insert_documents(dummy)
        
        # 🟢 字典 Key 依然存中文 new_name，方便 UI 显示
        known_collections[new_name] = new_store
        
        updated = list(known_collections.keys())
        return gr.update(choices=updated, value=new_name), f"✅ 创建成功: {new_name}"
    except Exception as e:
        return gr.update(), f"❌ 创建失败: {e}"

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
            shutil.rmtree(img_dir)
            msg += " (关联图片已清理)"
    except: pass
    
    return msg

def delete_collection_ui(name):
    ready, msg = check_ready()
    if not ready: return gr.update(), msg
    if not name: return gr.update(), "请选择要删除的库"
    
    alias = "delete_conn"
    try:
        connections.connect(alias=alias, uri=os.environ.get("MILVUS_URI"), token=os.environ.get("MILVUS_TOKEN"))
        
        # 必须把 UI 显示的中文名，转回 Milvus 内部存储的 encoded 名字
        real_milvus_name = encode_name(name) 
        
        # 使用 real_milvus_name 去检查和删除
        if utility.has_collection(real_milvus_name, using=alias): 
            utility.drop_collection(real_milvus_name, using=alias)
        if name in known_collections: 
            del known_collections[name]
        
        img_path = os.path.join(ASSET_DIR, name)
        if os.path.exists(img_path): shutil.rmtree(img_path)
        
        updated = list(known_collections.keys())
        val = updated[0] if updated else None
        return gr.update(choices=updated, value=val), f"🗑️ 已删除: {name}"
    
    except Exception as e:
        return gr.update(), f"❌ 删除失败: {e}"
    
    finally:
        try:
            connections.disconnect(alias)
        except: pass

def refresh_all_dropdowns():
    if not system_ready: return gr.update(), gr.update(), gr.update()
    new_cols = scan_remote_collections()
    return (
        gr.update(choices=new_cols), 
        gr.update(choices=new_cols), 
        gr.update(choices=new_cols)
    )