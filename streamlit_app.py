import streamlit as st
import json
import asyncio
import edge_tts
import tempfile
import os
from openai import OpenAI

# ============================================================
# 配置 DeepSeek（这里改成你的 API Key）
# ============================================================
DEEPSEEK_API_KEY = "sk-c64ff9443d6e45e894ab62c2b3c26261"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
)


# ============================================================
# 功能函数
# ============================================================
def remove_words_by_llm(text: str, n: int):
    prompt = f"""
你是一个严格的英语练习助手。给定英文原文和需要删除的单词数量N，请：

规则：
1. 只删除有实际意义的单词（名词、动词、形容词、副词）
2. 禁止删除：冠词、介词、连词、标点、数字
3. 删除位置用 "_____" 表示，前后各留一个空格
4. 返回纯 JSON 格式

原文：{text}
N：{n}

返回格式：{{"blank_text": "...", "removed_words": ["..."]}}
"""
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    result_text = response.choices[0].message.content
    result_text = result_text.replace("```json", "").replace("```", "").strip()
    return json.loads(result_text)


async def text_to_speech_async(text: str):
    communicate = edge_tts.Communicate(text, "en-US-JennyNeural")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        tmp_path = tmp.name
    await communicate.save(tmp_path)
    with open(tmp_path, "rb") as f:
        audio_bytes = f.read()
    os.unlink(tmp_path)
    return audio_bytes


def text_to_speech(text: str):
    return asyncio.run(text_to_speech_async(text))


def evaluate_answers(original: str, correct: list, user: list):
    if len(user) < len(correct):
        user += [""] * (len(correct) - len(user))

    prompt = f"""
严格评判听写答案。逐空比对。

原文：{original}
正确答案：{correct}
用户答案：{user}

规则：拼写、时态、单复数必须完全正确（大小写不区分）
返回JSON格式，只返回JSON，不要有其他文字：
{{"results": [{{"is_correct": true/false, "correct_answer": "正确答案", "suggestion": "提示"}}]}}

注意：用户答案在 {user} 中，请逐一比对。
"""
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    result_text = response.choices[0].message.content
    result_text = result_text.replace("```json", "").replace("```", "").strip()
    result = json.loads(result_text)

    # 把用户答案添加到结果中
    for i, r in enumerate(result["results"]):
        r["user_answer"] = user[i] if i < len(user) else ""

    correct_count = sum(1 for r in result["results"] if r["is_correct"])
    result["summary"] = {
        "total": len(correct),
        "correct_count": correct_count,
        "score": round(correct_count / len(correct) * 100, 1)
    }
    return result


# ============================================================
# 页面界面
# ============================================================
st.set_page_config(page_title="英语听力练习系统", page_icon="🎧")
st.title("🎧 英语听力练习系统")
st.markdown("听音频，填单词，AI 严格评判")

# 初始化
if "step" not in st.session_state:
    st.session_state.step = "input"

# ========== 第一步：输入原文 ==========
if st.session_state.step == "input":
    st.subheader("📝 输入英文原文")
    original_text = st.text_area("", height=120, placeholder="例如：The quick brown fox jumps over the lazy dog")
    n = st.selectbox("去掉几个单词？", [1, 2, 3, 4, 5], index=1)

    if st.button("开始练习", type="primary"):
        if not original_text.strip():
            st.error("请输入英文原文")
        else:
            with st.spinner("生成中..."):
                try:
                    result = remove_words_by_llm(original_text, n)
                    audio_bytes = text_to_speech(original_text)

                    st.session_state.original_text = original_text
                    st.session_state.blank_text = result["blank_text"]
                    st.session_state.removed_words = result["removed_words"]
                    st.session_state.audio_bytes = audio_bytes
                    st.session_state.step = "exercise"
                    st.rerun()
                except Exception as e:
                    st.error(f"失败：{e}")

# ========== 第二步：听写练习 ==========
elif st.session_state.step == "exercise":
    st.subheader("📝 带空白的文本")
    st.info(st.session_state.blank_text)

    st.subheader("🔊 听音频")
    st.audio(st.session_state.audio_bytes, format="audio/mp3")

    st.subheader("✏️ 填写缺失的单词")
    st.caption(f"共 {len(st.session_state.removed_words)} 个单词，按顺序用空格分隔")
    user_input = st.text_input("你的答案", placeholder="例如：brown jumps dog")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("提交答案", type="primary"):
            if not user_input.strip():
                st.error("请填写答案")
            else:
                answers = user_input.strip().split()
                if len(answers) != len(st.session_state.removed_words):
                    st.error(f"需要 {len(st.session_state.removed_words)} 个，你填了 {len(answers)} 个")
                else:
                    with st.spinner("评判中..."):
                        try:
                            result = evaluate_answers(
                                st.session_state.original_text,
                                st.session_state.removed_words,
                                answers
                            )
                            st.session_state.result = result
                            st.session_state.user_answers = answers
                            st.session_state.step = "result"
                            st.rerun()
                        except Exception as e:
                            st.error(f"失败：{e}")

    with col2:
        if st.button("重新开始"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

# ========== 第三步：显示结果 ==========
elif st.session_state.step == "result":
    result = st.session_state.result
    score = result["summary"]["score"]
    correct = result["summary"]["correct_count"]
    total = result["summary"]["total"]

    if score == 100:
        st.success(f"🎉 得分：{score}% （{correct}/{total}） 全对！")
    else:
        st.info(f"📊 得分：{score}% （{correct}/{total}）")

    st.subheader("逐空详情")
    for i, res in enumerate(result["results"], 1):
        if res["is_correct"]:
            st.success(f"✅ 第{i}空：{res['user_answer']} ✓")
        else:
            st.error(f"❌ 第{i}空：你填 '{res['user_answer']}' → 正确答案 '{res['correct_answer']}'")
            st.caption(f"💡 {res['suggestion']}")

    if st.button("新的练习", type="primary"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()