"""
General file-tools router for Bot-File-School.

Available to all users via the main menu "🛠 ابزارهای فایل".
- Several photos -> one PDF
- Word (.docx) -> PDF  (needs LibreOffice on the host)
- PDF -> Word (.docx)
Every step offers a "❌ لغو عملیات" button and never sends files outside
the bot itself. Admins additionally can convert saved notes (admin.py).
"""

from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

import models
import keyboards
import convert
from logger import logger

router = Router()


class FileToolsFlow(StatesGroup):
    waiting_images = State()      # collect multiple photos
    waiting_word = State()        # waiting for .docx
    waiting_pdf = State()         # waiting for .pdf
    entering_name = State()       # output file name


# callback of the menu the user came from (menu_tools | admin_main_back |
# menu_make_pdf). Stored in FSM so every back/cancel/finish returns there.
def _back_to(data: dict) -> str:
    return data.get("back_to", "menu_tools")


async def _remember_back(state: FSMContext, back_to: str):
    await state.update_data(back_to=back_to)


@router.callback_query(F.data == "tools_cancel")
async def tools_cancel_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    back_to = _back_to(data)
    await state.clear()
    await callback.message.edit_text(
        "❌ عملیات لغو شد.",
        reply_markup=keyboards.file_tools_keyboard(back_to),
    )


@router.callback_query(F.data.startswith("class_add"))
async def class_add_cancel_hook(callback: CallbackQuery, state: FSMContext):
    """Class-add flow starts from the admin panel; remember it for cancel."""
    # Only run remembering; the real handler in admin.py runs first
    # (router order: admin router loads before filetools in main.py) so
    # this fallback just guarantees back_to is set.
    if not (await state.get_data()).get("back_to"):
        await _remember_back(state, "admin_main_back")


# ─── Images → PDF ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "tool_images_pdf")
async def tool_images_pdf_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(FileToolsFlow.waiting_images)
    await state.update_data(img_paths=[])
    await callback.message.edit_text(
        "🖼 <b>تصاویر → PDF</b>\n\n"
        "یک یا چند عکس ارسال کنید (به‌ترتیب). سپس دکمه «بریس» را بزنید:",
        reply_markup=keyboards.cancel_keyboard("tools_cancel"),
        parse_mode="HTML",
    )


@router.message(StateFilter(FileToolsFlow.waiting_images), F.photo)
async def tool_images_collect(message: Message, state: FSMContext):
    import tempfile, os, hashlib
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    data = await state.get_data()
    dest_dir = Path(convert.TEMP_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = hashlib.md5(f"{message.from_user.id}{message.message_id}".encode()).hexdigest()[:16] + ".jpg"
    path = dest_dir / fname
    await message.bot.download(message.photo[-1], destination=path)

    paths = data.get("img_paths", []) or []
    paths.append(str(path))
    await state.update_data(img_paths=paths)

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=f"🧷 بررسی ({len(paths)} عکس)", callback_data="tool_images_done"),
        InlineKeyboardButton(text="❌ لغو عملیات", callback_data="tools_cancel"),
    )
    await message.answer(f"✅ عکس {len(paths)} ثبت شد. اگر عکس دیگری هست بفرستید یا «بریس» را بزنید:",
                         reply_markup=kb.as_markup())


@router.message(StateFilter(FileToolsFlow.waiting_images))
async def tool_images_not_photo(message: Message):
    await message.answer("❌ لطفاً فقط عکس ارسال کنید:")


@router.callback_query(F.data == "tool_images_done")
async def tool_images_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("img_paths"):
        await callback.answer("❌ هیچ عکسی دریافت نشده!", show_alert=True)
        return
    await state.set_state(FileToolsFlow.entering_name)
    await callback.message.edit_text(
        "✏️ نام فایل PDF خروجی را ارسال کنید (بدون پسوند):",
        reply_markup=keyboards.cancel_keyboard("tools_cancel"),
    )


@router.message(StateFilter(FileToolsFlow.entering_name), F.text)
async def tool_images_name(message: Message, state: FSMContext):
    name = convert.safe_name(message.text, "converted")
    data = await state.get_data()
    back_to = _back_to(data)
    out = Path(convert.TEMP_DIR) / f"{name}.pdf"
    try:
        convert.images_to_pdf([Path(p) for p in data["img_paths"]], out)
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ خطا در ساخت PDF: {e}")
        return
    await state.clear()
    try:
        await message.answer_document(out, caption=f"📄 {name}.pdf آماده شد ✅")
    except Exception as e:
        await message.answer(f"❌ خطا در ارسال فایل: {e}")
    finally:
        for p in data["img_paths"]:
            Path(p).unlink(missing_ok=True)
        out.unlink(missing_ok=True)
    await message.answer("🛠 گزینه دیگری لازم دارید؟", reply_markup=keyboards.file_tools_keyboard(back_to))
    await models.add_convert_job(message.from_user.id, "images", "pdf", output_type=str(out.name))


# ─── Word → PDF ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "tool_word_pdf")
async def tool_word_pdf_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(FileToolsFlow.waiting_word)
    await callback.message.edit_text(
        "📄 <b>Word → PDF</b>\n\nفایل Word (‌.docx) را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("tools_cancel"),
        parse_mode="HTML",
    )


@router.message(StateFilter(FileToolsFlow.waiting_word), F.document)
async def tool_word_receive(message: Message, state: FSMContext):
    doc = message.document
    if not (doc.file_name or "").lower().endswith((".docx", ".doc")):
        await message.answer("❌ فقط .docx پشتیبانی می‌شود. دوباره ارسال کنید:")
        return
    dest_dir = convert.TEMP_DIR
    src = dest_dir / convert.safe_name(doc.file_name or "file", "file")
    back_to = _back_to(await state.get_data())
    await message.bot.download(doc, destination=src)
    await state.clear()
    try:
        out_pdf = convert.word_to_pdf(src, dest_dir)
    except Exception as e:
        await message.answer(f"❌ {e}", reply_markup=keyboards.file_tools_keyboard(back_to))
        src.unlink(missing_ok=True)
        return
    try:
        await message.answer_document(out_pdf, caption="✅ فایل PDF آماده شد")
        await models.add_convert_job(message.from_user.id, "docx", "pdf", output_type=out_pdf.name)
    except Exception as e:
        await message.answer(f"❌ خطا در ارسال: {e}")
    finally:
        src.unlink(missing_ok=True)
        out_pdf.unlink(missing_ok=True)
    await message.answer("🛠 گزینه دیگری لازم دارید؟", reply_markup=keyboards.file_tools_keyboard(back_to))


# ─── PDF → Word ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "tool_pdf_word")
async def tool_pdf_word_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(FileToolsFlow.waiting_pdf)
    await callback.message.edit_text(
        "📝 <b>PDF → Word</b>\n\nفایل PDF را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("tools_cancel"),
        parse_mode="HTML",
    )


@router.message(StateFilter(FileToolsFlow.waiting_pdf), F.document)
async def tool_pdf_receive(message: Message, state: FSMContext):
    doc = message.document
    if not (doc.file_name or "").lower().endswith(".pdf"):
        await message.answer("❌ فقط .pdf پشتیبانی می‌شود. دوباره ارسال کنید:")
        return
    dest_dir = convert.TEMP_DIR
    src = dest_dir / convert.safe_name(doc.file_name or "file", "file")
    back_to = _back_to(await state.get_data())
    await message.bot.download(doc, destination=src)
    out = dest_dir / (src.stem + ".docx")
    try:
        convert.pdf_to_word(src, out)
    except Exception as e:
        await message.answer(f"❌ خطا در تبدیل: {e}", reply_markup=keyboards.file_tools_keyboard(back_to))
        src.unlink(missing_ok=True)
        return
    try:
        await message.answer_document(out, caption="✅ فایل Word آماده شد")
        await models.add_convert_job(message.from_user.id, "pdf", "docx", output_type=out.name)
    except Exception as e:
        await message.answer(f"❌ خطا در ارسال: {e}")
    finally:
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
    await message.answer("🛠 گزینه دیگری لازم دارید؟", reply_markup=keyboards.file_tools_keyboard(back_to))


@router.callback_query(F.data == "tool_saved_pdf")
async def tool_saved_pdf(callback: CallbackQuery):
    """Conversion of saved notes is admin-managed (see admin.py)."""
    await callback.answer()
    await callback.answer("این گزینه فقط برای ادمین فعال است؛ از پنل مدیریت استفاده کنید.", show_alert=True)
