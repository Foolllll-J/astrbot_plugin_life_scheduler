import json
import os
import re
import datetime
import asyncio
import random
import aiofiles
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Literal, Callable, Awaitable

try:
    import holidays
except ImportError:
    holidays = None

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api import logger
from astrbot.api.all import Star, Context, Plain, Image
from astrbot.core.star.star_tools import StarTools
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.core import html_renderer

# --- Config Definitions ---

@dataclass
class ChatReference:
    umo: str  # unified_msg_origin
    count: int = 20
    
    @staticmethod
    def from_dict(data: dict) -> 'ChatReference':
        if not isinstance(data, dict):
            return ChatReference(umo="")
        return ChatReference(
            umo=str(data.get("umo", "")),
            count=int(data.get("count", 20))
        )
    
    def to_dict(self) -> dict:
        return {"umo": self.umo, "count": self.count}

# --- 多样性元素池 ---

# 今日主题池
DAILY_THEMES = [
    "探索日",      # 尝试新事物、去新地方
    "社交日",      # 与朋友/同事互动为主
    "宅家日",      # 享受居家时光
    "工作日",      # 专注工作/学习
    "自我提升日",  # 学习新技能、阅读
    "休闲放松日",  # 纯粹的放松和享受
    "创意日",      # 做手工、画画、写作等创作活动
    "运动日",      # 以运动健身为主题
    "整理日",      # 整理房间、清理杂物、规划未来
    "美食日",      # 探索美食、尝试烹饪
    "文艺日",      # 看电影、听音乐、逛展览
    "随性漫游日",  # 没有固定计划，随心所欲
]

# 心情色彩池
MOOD_COLORS = [
    "慵懒",    # 懒洋洋的、不想动
    "活力",    # 精力充沛、积极向上
    "优雅",    # 从容淡定、气质出众
    "俏皮",    # 活泼可爱、调皮
    "神秘",    # 若隐若现、引人遐想
    "温柔",    # 柔和细腻、体贴入微
    "冷艳",    # 高冷中带着魅力
    "甜美",    # 可爱甜蜜、少女心
    "知性",    # 成熟稳重、有内涵
    "随性",    # 自在洒脱、不拘小节
    "浪漫",    # 充满幻想和情调
    "清新",    # 干净利落、自然纯粹
]

# 穿搭风格池
OUTFIT_STYLES = [
    "知性学院风",      # 衬衫、百褶裙、眼镜、书卷气
    "街头休闲风",      # 卫衣、牛仔裤、运动鞋
    "温柔淑女风",      # 长裙、开衫、珍珠饰品
    "酷飒中性风",      # 西装外套、阔腿裤、短发利落
    "慵懒居家风",      # 宽松毛衣、软糯睡衣、兔耳朵拖鞋
    "精致约会风",      # 小裙子、高跟鞋、精致妆容
    "运动活力风",      # 瑜伽服、运动背心、马尾辫
    "日系森女风",      # 棉麻长裙、草编包、自然妆
    "法式优雅风",      # 碎花裙、贝雷帽、红唇
    "韩系甜美风",      # 针织开衫、短裙、发带
    "复古文艺风",      # 高腰裤、衬衫、vintage饰品
    "极简都市风",      # 黑白灰基础色、利落剪裁
    "甜酷混搭风",      # 可爱元素+帅气单品混搭
    "民族风情风",      # 刺绣、流苏、民族图案
    "暗黑系风格",      # 黑色为主、皮革、金属饰品
]

# 日程类型池
SCHEDULE_TYPES = [
    "户外活动型",    # 公园、郊游、逛街
    "社交聚会型",    # 和朋友见面、聚餐
    "独处充电型",    # 一个人安静地做喜欢的事
    "技能学习型",    # 学习新技能、看网课
    "随性漫游型",    # 没有固定计划，走到哪算哪
    "家务整理型",    # 打扫、整理、收纳
    "工作专注型",    # 高效完成工作任务
    "休闲娱乐型",    # 看剧、玩游戏、听音乐
    "健身运动型",    # 健身房、跑步、瑜伽
    "美食探索型",    # 寻找美食、烹饪
    "文化艺术型",    # 看展、看电影、逛书店
    "购物采买型",    # 逛商场、网购
]


@dataclass
class SchedulerConfig:
    schedule_time: str = "07:00"
    reference_history_days: int = 3
    reference_chats: List[ChatReference] = field(default_factory=list)
    prompt_template: str = """# Role: Life Scheduler
请根据以下信息，为自己规划一份今天的生活安排。请代入你的人设，生成的内容应富有生活气息和独特性。

## Context
- 日期：{date_str} {weekday} {holiday}
- 人设：{persona_desc}

## 🎲 今日创意约束（必须遵循）
- 今日主题：【{daily_theme}】- 请围绕这个主题安排今天的主要活动
- 心情色彩：【{mood_color}】- 今天的整体情绪基调，影响穿搭和活动选择
- 推荐穿搭风格：【{outfit_style}】- 今天的穿搭应该偏向这个风格
- 日程类型：【{schedule_type}】- 今天的日程安排应该偏向这个类型

## ⚠️ 多样性要求（重要）
1. **穿搭必须具体且独特**：不要用"修身针织裙"这种泛泛的描述，要有具体的颜色、款式、搭配细节
2. **日程必须有亮点**：每天至少有一个与众不同的活动或小确幸
3. **避免重复模式**：不要总是"早起-家务-午餐-下午茶-等主人回来"的固定套路

## 🚫 需要避免的重复内容
以下是最近几天的安排，今天必须有明显差异，不要重复相似的穿搭和活动：
{history_schedules}

## 💡 参考信息
- 近期对话记忆（可以从中获取灵感）：
{recent_chats}

## Tasks
1. outfit: 设计今日穿搭。{outfit_desc}请基于【{outfit_style}】风格，但要有创意变化。
2. schedule: 规划今日日程。围绕【{daily_theme}】主题和【{schedule_type}】类型，融入【{mood_color}】的情绪色彩。

## Output Format
请务必严格遵循 JSON 格式返回，不要包含 Markdown 代码块标记（如 ```json），也不要包含任何额外的解释文本。
格式如下：
{{
    "outfit": "具体描述今日穿搭（包含颜色、款式、配饰等细节）",
    "schedule": "生动描述今日日程（要有故事感和画面感，避免流水账）"
}}
"""
    outfit_desc: str = "具体描述颜色、款式、材质和搭配细节，让穿搭有画面感。"

    @staticmethod
    def from_dict(data: dict) -> 'SchedulerConfig':
        config = SchedulerConfig()
        if not isinstance(data, dict):
            return config
            
        config.schedule_time = data.get("schedule_time", "07:00")
        config.reference_history_days = data.get("reference_history_days", 3)
        
        refs = data.get("reference_chats", [])
        if isinstance(refs, list):
            config.reference_chats = [ChatReference.from_dict(r) for r in refs if isinstance(r, dict)]
        
        if "prompt_template" in data:
            config.prompt_template = data["prompt_template"]
        if "outfit_desc" in data:
            config.outfit_desc = data["outfit_desc"]
            
        return config

    def to_dict(self) -> dict:
        return {
            "schedule_time": self.schedule_time,
            "reference_history_days": self.reference_history_days,
            "reference_chats": [r.to_dict() for r in self.reference_chats],
            "prompt_template": self.prompt_template,
            "outfit_desc": self.outfit_desc
        }

# --- Helper Functions ---

def extract_json_from_text(text: str) -> Optional[dict]:
    """
    Extracts the first JSON object from the text using a stack-based approach
    to handle nested braces correctly.
    """
    text = text.strip()
    # Remove markdown code blocks
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
    
    start_index = text.find('{')
    if start_index == -1:
        return None
    
    brace_level = 0
    in_string = False
    escape = False
    
    for i, char in enumerate(text[start_index:], start=start_index):
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == '{':
                brace_level += 1
            elif char == '}':
                brace_level -= 1
                if brace_level == 0:
                    json_str = text[start_index:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                         pass
    return None

async def get_recent_chats(context: Context, umo: str, count: int) -> str:
    """获取指定会话的最近聊天记录"""
    try:
        # 尝试从 conversation_manager 获取
        # session = MessageSesion.from_str(umo) # unused
        # 1. 获取当前 conversation_id
        cid = await context.conversation_manager.get_curr_conversation_id(umo)
        if not cid:
            return "无最近对话记录"
            
        # 2. 获取 conversation
        conv = await context.conversation_manager.get_conversation(umo, cid)
        if not conv or not conv.history:
            return "无最近对话记录"
            
        # 3. 解析 history
        history = json.loads(conv.history)
        
        # 4. 取最近 count 条
        recent = history[-count:] if count > 0 else []
        
        # 5. 格式化
        formatted = []
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "user":
                formatted.append(f"用户: {content}")
            elif role == "assistant":
                formatted.append(f"我: {content}")
                
        return "\n".join(formatted)
        
    except Exception as e:
        logger.error(f"Failed to get recent chats for {umo}: {e}")
        return "获取对话记录失败"

def get_holiday_info(date: datetime.date) -> str:
    """获取节日信息（中国）"""
    if holidays is None:
        return ""
    
    try:
        cn_holidays = holidays.CN()
        holiday_name = cn_holidays.get(date)
        if holiday_name:
            return f"今天是 {holiday_name}"
    except Exception:
        return ""
    return ""


# --- Scheduler Class ---

class LifeScheduler:
    def __init__(self, schedule_time: str, task: Callable[[], Awaitable[None]]):
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.schedule_time = schedule_time
        self.task = task
        self.job = None

    def start(self):
        try:
            hour, minute = self.schedule_time.split(":")
            self.job = self.scheduler.add_job(
                self.task,
                'cron',
                hour=hour,
                minute=minute,
                id='daily_schedule_gen'
            )
            self.scheduler.start()
            logger.info(f"Life Scheduler started at {hour}:{minute}")
        except Exception as e:
            logger.error(f"Failed to setup scheduler: {e}")

    def update_schedule_time(self, new_time: str):
        if new_time == self.schedule_time:
            return
        
        try:
            hour, minute = new_time.split(":")
            self.schedule_time = new_time
            if self.job:
                self.job.reschedule('cron', hour=hour, minute=minute)
                logger.info(f"Life Scheduler rescheduled to {hour}:{minute}")
        except Exception as e:
            logger.error(f"Failed to update scheduler: {e}")

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

# --- Main Class ---

class Main(Star):
    def __init__(self, context: Context, *args, **kwargs) -> None:
        super().__init__(context)
        self.context = context
        
        self.base_dir = StarTools.get_data_dir("astrbot_plugin_life_scheduler")
        self.config_path = self.base_dir / "config.json"
        self.data_path = self.base_dir / "data.json"
        
        self.generation_lock = asyncio.Lock()
        self.data_lock = asyncio.Lock()
        self.failed_dates = set() # Track dates where generation failed to avoid infinite retries
        
        self.config = self.load_config()
        self.schedule_data = self.load_data()
        
        self.scheduler = LifeScheduler(self.config.schedule_time, self.daily_schedule_task)
        self.scheduler.start()

    def load_config(self) -> SchedulerConfig:
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return SchedulerConfig.from_dict(data)
            except json.JSONDecodeError:
                logger.error(f"Config file is corrupted: {self.config_path}")
            except Exception as e:
                logger.exception(f"Failed to load config: {e}")
        return SchedulerConfig()

    async def save_config(self):
        try:
            # Atomic write
            temp_path = self.config_path.with_suffix(".tmp")
            async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(self.config.to_dict(), indent=4, ensure_ascii=False))
            
            if os.name == 'nt' and self.config_path.exists():
                 os.remove(self.config_path) # Windows replace fix
            os.replace(temp_path, self.config_path)
        except Exception as e:
            logger.exception(f"Failed to save config: {e}")

    def load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            try:
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Data file is corrupted: {self.data_path}")
            except Exception as e:
                logger.exception(f"Failed to load data: {e}")
        return {}

    async def save_data(self):
        async with self.data_lock:
            try:
                # Atomic write
                temp_path = self.data_path.with_suffix(".tmp")
                async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(self.schedule_data, indent=4, ensure_ascii=False))
                
                if os.name == 'nt' and self.data_path.exists():
                    os.remove(self.data_path) # Windows replace fix
                os.replace(temp_path, self.data_path)
            except Exception as e:
                logger.exception(f"Failed to save data: {e}")

    async def daily_schedule_task(self):
        """定时任务：生成日程"""
        logger.info("Starting daily schedule generation task...")
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        schedule_info = await self.generate_schedule_with_llm()
        if not schedule_info:
            logger.error("Failed to generate schedule.")
            return

        async with self.data_lock:
            self.schedule_data[today_str] = schedule_info
        await self.save_data()
        
    async def generate_schedule_with_llm(self) -> Optional[Dict[str, str]]:
        """调用 LLM 生成日程"""
        today = datetime.datetime.now()
        date_str = today.strftime("%Y年%m月%d日")
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][today.weekday()]
        holiday = get_holiday_info(today.date())
        
        # 0. 随机选择今日的创意约束元素
        daily_theme = random.choice(DAILY_THEMES)
        mood_color = random.choice(MOOD_COLORS)
        outfit_style = random.choice(OUTFIT_STYLES)
        schedule_type = random.choice(SCHEDULE_TYPES)
        
        logger.info(f"Today's diversity elements: theme={daily_theme}, mood={mood_color}, outfit={outfit_style}, schedule={schedule_type}")
        
        # 1. 收集上下文
        # 历史日程 - 现在用于"避免重复"而非"参考模仿"
        history_schedules = []
        for i in range(1, self.config.reference_history_days + 1):
            past_date = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            if past_date in self.schedule_data:
                past_info = self.schedule_data[past_date]
                outfit_info = past_info.get('outfit', '')[:50]
                schedule_info = past_info.get('schedule', '')[:80]
                history_schedules.append(f"[{past_date}] 穿搭: {outfit_info}... | 日程: {schedule_info}...")
        history_schedules_str = "\n".join(history_schedules) if history_schedules else "（无历史记录，可以自由发挥）"

        # 近期对话
        recent_chats_str = ""
        if self.config.reference_chats:
            chats = []
            for ref in self.config.reference_chats:
                chat_content = await get_recent_chats(self.context, ref.umo, ref.count)
                if chat_content:
                    chats.append(f"--- 会话 {ref.umo} ---\n{chat_content}")
            recent_chats_str = "\n".join(chats)
        if not recent_chats_str:
            recent_chats_str = "无近期对话"

        # 2. 构造 Prompt
        persona_desc = "你是一个充满活力、热爱生活、情感丰富的AI伙伴。"
        
        # 尝试从 PersonaManager 获取当前人设
        if hasattr(self.context, "persona_manager"):
            try:
                persona = await self.context.persona_manager.get_default_persona_v3()
                # 兼容 dict 访问和属性访问
                if hasattr(persona, "get"):
                    p_prompt = persona.get("prompt", "")
                elif hasattr(persona, "prompt"):
                    p_prompt = persona.prompt
                else:
                    p_prompt = ""
                
                if p_prompt:
                    persona_desc = p_prompt
            except Exception as e:
                logger.warning(f"Failed to get persona from manager: {e}")

        prompt = self.config.prompt_template.format(
            date_str=date_str,
            weekday=weekday,
            holiday=holiday,
            persona_desc=persona_desc,
            daily_theme=daily_theme,
            mood_color=mood_color,
            outfit_style=outfit_style,
            schedule_type=schedule_type,
            history_schedules=history_schedules_str,
            recent_chats=recent_chats_str,
            outfit_desc=self.config.outfit_desc
        )

        try:
            content = ""
            provider = self.context.get_using_provider()
            if not provider:
                logger.error("No LLM provider available.")
                return None
            
            # session_id 必须是 str，如果没有特定会话，可以传空字符串或特定标识
            # 使用特定 session_id 来隔离上下文
            gen_session_id = "life_scheduler_gen"
            try:
                response = await provider.text_chat(prompt, session_id=gen_session_id)
                content = response.completion_text
                
                # JSON 提取
                json_data = extract_json_from_text(content)
                if json_data:
                    return json_data
                else:
                    logger.warning(f"LLM response not in JSON format or decoding failed: {content}")
                    # Fallback
                    return {"outfit": "日常休闲装", "schedule": content}
            finally:
                # 任务完成后，清理该临时会话的历史记录，防止上下文无限增长
                try:
                    # life_scheduler_gen 作为 UMO，会创建一个 Conversation
                    cid = await self.context.conversation_manager.get_curr_conversation_id(gen_session_id)
                    if cid:
                        await self.context.conversation_manager.delete_conversation(gen_session_id, cid)
                        logger.debug(f"Cleaned up temporary session: {gen_session_id}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temporary session: {cleanup_error}")

        except Exception as e:
            logger.exception(f"Error calling LLM: {e}")
            return None

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """System Prompt 注入 & 懒加载"""
        # 防止无限递归：如果请求来自本插件的日程生成任务，直接忽略
        if req.session_id == "life_scheduler_gen":
            return

        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # Double-check locking pattern for lazy loading
        if today_str not in self.schedule_data and today_str not in self.failed_dates:
            async with self.generation_lock:
                # Re-check inside lock
                if today_str not in self.schedule_data and today_str not in self.failed_dates:
                    logger.info(f"Lazy loading schedule for {today_str}...")
                    schedule_info = await self.generate_schedule_with_llm()
                    if schedule_info:
                        async with self.data_lock:
                            self.schedule_data[today_str] = schedule_info
                        await self.save_data()
                    else:
                        logger.warning(f"Failed to lazy load schedule for {today_str}. Marking as failed to prevent infinite retries.")
                        self.failed_dates.add(today_str)
        
        if today_str in self.schedule_data:
            info = self.schedule_data[today_str]
            now_hour = datetime.datetime.now().hour
            
            # 根据时间段生成更自然的状态描述
            if now_hour < 6:
                time_context = "深夜/凌晨"
            elif now_hour < 9:
                time_context = "清晨"
            elif now_hour < 12:
                time_context = "上午"
            elif now_hour < 14:
                time_context = "中午"
            elif now_hour < 18:
                time_context = "下午"
            elif now_hour < 22:
                time_context = "晚上"
            else:
                time_context = "深夜"
            
            outfit = info.get('outfit', '')
            schedule = info.get('schedule', '')
            
            # 使用更隐晦的方式注入，强调这是内心状态而非需要表达的信息
            inject_text = f"""

[内在状态 - 仅供理解角色当前心境，无需在对话中提及]
时间感知：{time_context}
穿着状态：{outfit}
当日背景：{schedule}

[对话原则]
- 专注于用户当前的话题和需求
- 像真人一样自然对话，不解释自己在做什么、穿什么、在哪里
- 只有当用户明确问起时，才简短回应相关问题
- 上述内在状态只影响你的语气和情绪色彩，不作为对话内容"""
            
            req.system_prompt += inject_text

    @filter.command("life")
    async def life_command(self, event: AstrMessageEvent, action: str = "", param: str = ""):
        """
        生活日程管理指令
        /life show - 查看今日日程
        /life regenerate - 重新生成今日日程
        /life time [HH:MM] - 设置每日生成时间
        """
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        umo = event.unified_msg_origin
        
        result = None

        if action == "show":
            info = self.schedule_data.get(today_str)
            if info:
                # 如果已有日程，直接返回日程信息字符串，让 AstrBot 处理发送
                text_content = f"📅 {today_str}\n👗 今日穿搭：{info.get('outfit')}\n📝 日程安排：\n{info.get('schedule')}"
                result = MessageEventResult().message(text_content)
            else:
                # 尝试生成
                await self.context.send_message(umo, MessageChain([Plain("今日尚未生成日程，正在为您生成...")]))
                schedule_info = await self.generate_schedule_with_llm()
                if schedule_info:
                    async with self.data_lock:
                        self.schedule_data[today_str] = schedule_info
                    await self.save_data()
                    text_content = f"📅 {today_str}\n👗 今日穿搭：{schedule_info.get('outfit')}\n📝 日程安排：\n{schedule_info.get('schedule')}"
                    result = MessageEventResult().message(text_content)
                else:
                    result = MessageEventResult().message("生成失败，请检查日志。")
        
        elif action == "regenerate":
            await self.context.send_message(umo, MessageChain([Plain("正在重新生成日程...")]))
            schedule_info = await self.generate_schedule_with_llm()
            if schedule_info:
                async with self.data_lock:
                    self.schedule_data[today_str] = schedule_info
                await self.save_data()
                text_content = f"📅 {today_str}\n👗 今日穿搭：{schedule_info.get('outfit')}\n📝 日程安排：\n{schedule_info.get('schedule')}"
                result = MessageEventResult().message(text_content)
            else:
                result = MessageEventResult().message("生成失败，请检查日志。")
        
        elif action == "time":
            if not param:
                 result = MessageEventResult().message("请提供时间，格式为 HH:MM，例如 /life time 07:30")
            
            elif not re.match(r"^\d{2}:\d{2}$", param):
                result = MessageEventResult().message("时间格式错误，请使用 HH:MM 格式。")
            
            else:
                try:
                    self.scheduler.update_schedule_time(param)
                    self.config.schedule_time = param
                    await self.save_config()
                    result = MessageEventResult().message(f"已将每日日程生成时间更新为 {param}。")
                except Exception as e:
                    result = MessageEventResult().message(f"设置失败: {e}")

        else:
            result = MessageEventResult().message(
                "指令用法：\n"
                "/life show - 查看日程\n"
                "/life regenerate - 重新生成\n"
                "/life time <HH:MM> - 设置生成时间"
            )
        
        if result:
            yield result

    async def terminate(self):
        """插件卸载时清理"""
        self.scheduler.shutdown()
