# app/bot.py
# MediaPilot Bot 主程序入口

import logging
import os
from typing import Any, Dict, List, Optional

import qbittorrentapi
import requests
from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# 配置日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# 加载 .env 文件中的环境变量
load_dotenv()

# --- API 配置 ---
RADARR_URL = f"http://{os.getenv('RADARR_HOST')}:{os.getenv('RADARR_PORT')}"
RADARR_API_KEY = os.getenv("RADARR_API_KEY")
SONARR_URL = f"http://{os.getenv('SONARR_HOST')}:{os.getenv('SONARR_PORT')}"
SONARR_API_KEY = os.getenv("SONARR_API_KEY")


# --- 辅助函数 ---


def format_speed(speed_bytes: int) -> str:
    """将字节/秒格式化为可读的速度字符串"""
    if speed_bytes < 1024:
        return f"{speed_bytes} B/s"
    if speed_bytes < 1024**2:
        return f"{speed_bytes/1024:.2f} KB/s"
    if speed_bytes < 1024**3:
        return f"{speed_bytes/1024**2:.2f} MB/s"
    return f"{speed_bytes/1024**3:.2f} GB/s"


# --- Radarr API 封装 ---


def radarr_api_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """向 Radarr API 发送 GET 请求"""
    if params is None:
        params = {}
    params["apikey"] = RADARR_API_KEY
    try:
        response = requests.get(
            f"{RADARR_URL}/api/v3/{endpoint}", params=params, timeout=15
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Radarr API GET /api/v3/{endpoint} 请求失败: {e}")
        raise


def radarr_api_post(endpoint: str, json_data: Dict[str, Any]) -> Any:
    """向 Radarr API 发送 POST 请求"""
    try:
        response = requests.post(
            f"{RADARR_URL}/api/v3/{endpoint}",
            params={"apikey": RADARR_API_KEY},
            json=json_data,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Radarr API POST /api/v3/{endpoint} 请求失败: {e}")
        try:
            error_details = e.response.json()
            logger.error(f"Radarr API 错误详情: {error_details}")
            raise Exception(
                f"Radarr API 错误: {error_details[0].get('errorMessage') if isinstance(error_details, list) and error_details else str(e)}"
            ) from e
        except (ValueError, AttributeError, IndexError):
            raise Exception(f"Radarr API 错误: {str(e)}") from e


# --- Sonarr API 封装 ---


def sonarr_api_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """向 Sonarr API 发送 GET 请求"""
    if params is None:
        params = {}
    params["apikey"] = SONARR_API_KEY
    try:
        response = requests.get(
            f"{SONARR_URL}/api/v3/{endpoint}", params=params, timeout=15
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Sonarr API GET /api/v3/{endpoint} 请求失败: {e}")
        raise


def sonarr_api_post(endpoint: str, json_data: Dict[str, Any]) -> Any:
    """向 Sonarr API 发送 POST 请求"""
    try:
        response = requests.post(
            f"{SONARR_URL}/api/v3/{endpoint}",
            params={"apikey": SONARR_API_KEY},
            json=json_data,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Sonarr API POST /api/v3/{endpoint} 请求失败: {e}")
        try:
            error_details = e.response.json()
            logger.error(f"Sonarr API 错误详情: {error_details}")
            raise Exception(
                f"Sonarr API 错误: {error_details[0].get('errorMessage') if isinstance(error_details, list) and error_details else str(e)}"
            ) from e
        except (ValueError, AttributeError, IndexError):
            raise Exception(f"Sonarr API 错误: {str(e)}") from e


# --- Telegram 命令处理 ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """发送 /start 命令时的欢迎消息"""
    user = update.effective_user
    await update.message.reply_html(
        f"你好，{user.mention_html()}！\n\n"
        f"我是 MediaPilot Bot，你的媒体自动化助手。\n"
        f"Radarr 和 Sonarr 将会自动处理下载和整理，完成后 Emby 中会自动出现。\n\n"
        "使用 /help 查看所有可用命令。",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """发送 /help 命令时的帮助消息"""
    help_text = (
        "<b>可用命令:</b>\n"
        "/start - 开始与机器人交互\n"
        "/help - 显示此帮助消息\n"
        "/status - 查看所有后端服务的连接状态\n"
        "/search <code>&lt;电影名称&gt;</code> - 搜索并添加电影到 Radarr\n"
        "/series <code>&lt;剧集名称&gt;</code> - 搜索并添加剧集到 Sonarr"
    )
    await update.message.reply_html(help_text, disable_web_page_preview=True)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /status 命令，显示所有服务的连接状态"""
    msg = await update.message.reply_text("正在获取所有服务状态...")
    status_lines = ["<b>后端服务状态:</b>"]

    # 1. qBittorrent 状态
    qb_host, qb_port, qb_user, qb_pass = (
        os.getenv(k)
        for k in [
            "QBITTORRENT_HOST",
            "QBITTORRENT_PORT",
            "QBITTORRENT_USER",
            "QBITTORRENT_PASS",
        ]
    )
    try:
        qbt_client = qbittorrentapi.Client(
            host=qb_host, port=qb_port, username=qb_user, password=qb_pass
        )
        qbt_client.auth_log_in()
        qbt_version = qbt_client.app.version
        status_lines.append(f"✅ <b>qBittorrent:</b> 连接成功 (v{qbt_version})")
    except Exception as e:
        logger.error(f"qBittorrent status error: {e}")
        status_lines.append(f"❌ <b>qBittorrent:</b> 连接失败")

    # 2. Prowlarr 状态
    prowlarr_url = f"http://{os.getenv('PROWLARR_HOST')}:{os.getenv('PROWLARR_PORT')}"
    prowlarr_api_key = os.getenv("PROWLARR_API_KEY")
    try:
        response = requests.get(
            f"{prowlarr_url}/api/v1/system/status",
            params={"apikey": prowlarr_api_key},
            timeout=10,
        )
        response.raise_for_status()
        prowlarr_version = response.json().get("version", "N/A")
        status_lines.append(f"✅ <b>Prowlarr:</b> 连接成功 (v{prowlarr_version})")
    except Exception as e:
        logger.error(f"Prowlarr status error: {e}")
        status_lines.append(f"❌ <b>Prowlarr:</b> 连接失败")

    # 3. Radarr 状态
    try:
        radarr_status = radarr_api_get("system/status")
        radarr_version = radarr_status.get("version", "N/A")
        status_lines.append(f"✅ <b>Radarr:</b> 连接成功 (v{radarr_version})")
    except Exception as e:
        logger.error(f"Radarr status error: {e}")
        status_lines.append(f"❌ <b>Radarr:</b> 连接失败")

    # 4. Sonarr 状态
    try:
        sonarr_status = sonarr_api_get("system/status")
        sonarr_version = sonarr_status.get("version", "N/A")
        status_lines.append(f"✅ <b>Sonarr:</b> 连接成功 (v{sonarr_version})")
    except Exception as e:
        logger.error(f"Sonarr status error: {e}")
        status_lines.append(f"❌ <b>Sonarr:</b> 连接失败")

    await msg.edit_text("\n".join(status_lines), parse_mode="HTML")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /search 命令，使用 Radarr 查找电影并提供添加按钮"""
    if not context.args:
        await update.message.reply_text("用法: /search <电影名称>")
        return
    query = " ".join(context.args)
    msg = await update.message.reply_text(f"正在为“{query}”在 Radarr 中查找电影...")

    try:
        search_results = radarr_api_get("movie/lookup", params={"term": query})
        if not search_results:
            await msg.edit_text(f"🤷‍♂️ 未找到与“{query}”相关的电影。")
            return

        keyboard = []
        reply_text = f"🔎 “{query}”的电影搜索结果:\n"
        for movie in search_results[:5]:
            title = movie.get("title", "N/A")
            year = movie.get("year", "N/A")
            tmdb_id = movie.get("tmdbId", 0)

            if tmdb_id == 0:
                continue

            is_added = movie.get("id", 0) != 0
            button_text = "✅ 已添加" if is_added else "➕ 添加"
            callback_data = (
                f"add_movie|added" if is_added else f"select_quality|{tmdb_id}"
            )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{title} ({year}) - {button_text}", callback_data=callback_data
                    )
                ]
            )
        if not keyboard:
            await msg.edit_text(f"🤷‍♂️ 未找到与“{query}”相关的有效结果。")
            return

        await msg.edit_text(
            reply_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"search_command 错误: {e}")
        await msg.edit_text(f"❌ 搜索失败: {e}")


async def search_series_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """处理 /series 命令，使用 Sonarr 查找剧集并提供添加按钮"""
    if not context.args:
        await update.message.reply_text("用法: /series <剧集名称>")
        return
    query = " ".join(context.args)
    msg = await update.message.reply_text(f"正在为“{query}”在 Sonarr 中查找剧集...")

    try:
        search_results = sonarr_api_get("series/lookup", params={"term": query})
        if not search_results:
            await msg.edit_text(f"🤷‍♂️ 未找到与“{query}”相关的剧集。")
            return

        keyboard = []
        reply_text = f"🔎 “{query}”的剧集搜索结果:\n"
        for series in search_results[:5]:
            title = series.get("title", "N/A")
            year = series.get("year", "N/A")
            tvdb_id = series.get("tvdbId", 0)

            if tvdb_id == 0:
                continue

            is_added = series.get("id", 0) != 0
            button_text = "✅ 已添加" if is_added else "➕ 添加"
            callback_data = (
                f"add_series|added" if is_added else f"add_series|{tvdb_id}"
            )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{title} ({year}) - {button_text}", callback_data=callback_data
                    )
                ]
            )
        if not keyboard:
            await msg.edit_text(f"🤷‍♂️ 未找到与“{query}”相关的有效结果。")
            return

        await msg.edit_text(
            reply_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"search_series_command 错误: {e}")
        await msg.edit_text(f"❌ 搜索失败: {e}")



async def add_movie_button_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """处理添加电影按钮的回调，仅处理 'added' 状态"""
    cb_query = update.callback_query
    await cb_query.answer()

    action, status_or_tmdb_id = cb_query.data.split("|")

    if status_or_tmdb_id == "added":
        await cb_query.edit_message_text("✅ 这部电影已经在你的媒体库中了。")
        return

async def select_quality_profile_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """处理选择质量配置的回调，显示质量配置选项"""
    cb_query = update.callback_query
    await cb_query.answer()

    action, tmdb_id_str = cb_query.data.split("|")
    tmdb_id = int(tmdb_id_str)

    try:
        quality_profiles = radarr_api_get("qualityprofile")
        if not quality_profiles:
            await cb_query.edit_message_text("❌ 无法获取 Radarr 质量配置。")
            return

        keyboard = []
        for profile in quality_profiles:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        profile["name"],
                        callback_data=f"add_movie_with_quality|{tmdb_id}|{profile['id']}",
                    )
                ]
            )

        reply_markup = InlineKeyboardMarkup(keyboard)
        await cb_query.edit_message_text(
            f"请选择电影的质量配置 (TMDB ID: {tmdb_id}):", reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"select_quality_profile_handler 错误: {e}")
        await cb_query.edit_message_text(f"❌ 获取质量配置失败: {e}")


async def add_movie_with_quality_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """处理选择质量配置后的添加电影回调"""
    cb_query = update.callback_query
    await cb_query.answer()

    action, tmdb_id_str, quality_profile_id_str = cb_query.data.split("|")
    tmdb_id = int(tmdb_id_str)
    quality_profile_id = int(quality_profile_id_str)

    try:
        lookup_results = radarr_api_get(
            "movie/lookup", params={"term": f"tmdb:{tmdb_id}"}
        )
        if not lookup_results:
            await cb_query.edit_message_text("❌ 找不到该电影的详细信息。")
            return
        movie_to_add = lookup_results[0]

        root_folders = radarr_api_get("rootfolder")
        if not root_folders:
            await cb_query.edit_message_text("❌ Radarr 未配置根目录。")
            return
        root_folder_path = root_folders[0]["path"]

        add_payload = {
            "title": movie_to_add["title"],
            "tmdbId": movie_to_add["tmdbId"],
            "year": movie_to_add["year"],
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "images": movie_to_add["images"],
            "addOptions": {"searchForMovie": True},
        }

        added_movie = radarr_api_post("movie", json_data=add_payload)
        title = added_movie.get("title", "N/A")
        await cb_query.edit_message_text(
            f"✅ <b>{title}</b> 已成功添加到 Radarr 并开始搜索！", parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"add_movie_with_quality_handler 错误: {e}")
        if "already been added" in str(e):
            await cb_query.edit_message_text("✅ 这部电影已经在你的媒体库中了。")
        else:
            await cb_query.message.reply_text(f"❌ 添加电影时发生错误: {e}")



async def add_series_button_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """处理添加剧集按钮的回调"""
    cb_query = update.callback_query
    await cb_query.answer()

    action, tvdb_id_str = cb_query.data.split("|")

    if tvdb_id_str == "added":
        await cb_query.edit_message_text("✅ 这部剧集已经在你的媒体库中了。")
        return

    tvdb_id = int(tvdb_id_str)

    try:
        lookup_results = sonarr_api_get(
            "series/lookup", params={"term": f"tvdb:{tvdb_id}"}
        )
        if not lookup_results:
            await cb_query.edit_message_text("❌ 找不到该剧集的详细信息。")
            return
        series_to_add = lookup_results[0]

        quality_profiles = sonarr_api_get("qualityprofile")
        root_folders = sonarr_api_get("rootfolder")

        if not quality_profiles or not root_folders:
            await cb_query.edit_message_text("❌ Sonarr 未配置质量或根目录。")
            return

        quality_profile_id = quality_profiles[0]["id"]
        root_folder_path = root_folders[0]["path"]

        add_payload = {
            "title": series_to_add["title"],
            "tvdbId": series_to_add["tvdbId"],
            "year": series_to_add["year"],
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "images": series_to_add["images"],
            "seasons": series_to_add["seasons"],
            "addOptions": {
                "ignoreEpisodesWithFiles": False,
                "ignoreEpisodesWithoutFiles": False,
                "searchForMissingEpisodes": True,
            },
        }

        added_series = sonarr_api_post("series", json_data=add_payload)
        title = added_series.get("title", "N/A")
        await cb_query.edit_message_text(
            f"✅ <b>{title}</b> 已成功添加到 Sonarr 并开始搜索！", parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"add_series_button_handler 错误: {e}")
        if "already been added" in str(e):
            await cb_query.edit_message_text("✅ 这部剧集已经在你的媒体库中了。")
        else:
            await cb_query.message.reply_text(f"❌ 添加剧集时发生错误: {e}")


# --- 主函数 ---


def main() -> None:
    """启动机器人"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or "YOUR_TELEGRAM_BOT_TOKEN" in token:
        logger.error("错误：请在 .env 文件中设置有效的 TELEGRAM_BOT_TOKEN")
        return

    if not RADARR_API_KEY or "YOUR_RADARR_API_KEY" in RADARR_API_KEY:
        logger.error("错误：请在 .env 文件中设置有效的 RADARR_API_KEY")
        return
        
    if not SONARR_API_KEY or "YOUR_SONARR_API_KEY" in SONARR_API_KEY:
        logger.error("错误：请在 .env 文件中设置有效的 SONARR_API_KEY")
        return

    application = Application.builder().token(token).build()

    # 注册命令处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("series", search_series_command))

    # 注册回调处理器
    application.add_handler(
        CallbackQueryHandler(add_movie_button_handler, pattern=r"^add_movie\|added$")
    )
    application.add_handler(
        CallbackQueryHandler(select_quality_profile_handler, pattern=r"^select_quality\|")
    )
    application.add_handler(
        CallbackQueryHandler(add_movie_with_quality_handler, pattern=r"^add_movie_with_quality\|")
    )
    application.add_handler(
        CallbackQueryHandler(add_series_button_handler, pattern=r"^add_series\|")
    )

    logger.info("机器人正在启动...")
    application.run_polling()


if __name__ == "__main__":
    main()
