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
import asyncio
import uuid
import weakref

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, PhotoSize, Document
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

import models
import keyboards
import convert
from logger import logger

router = Router()


class FileToolsFlow(StatesGroup):
    waiting_single_image = State()
    waiting_images = State()      # collect multiple photos until "pdfs"
    finalizing_images = State()
    waiting_word = State()        # waiting for .docx
    waiting_pdf = State()         # waiting for .pdf


MAX_IMAGES_PER_PDF = 20
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 45 * 1024 * 1024
MAX_OUTPUT_PDF_BYTES = 49 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_TOTAL_IMAGE_PIXELS = 40_000_000

_image_flow_locks: weakref.WeakValueDictionary[
    tuple[int, int], asyncio.Lock
] = weakref.WeakValueDictionary()


def _flow_lock(user_id: int, chat_id: int) -> asyncio.Lock:
    return _image_flow_locks.setdefault((chat_id, user_id), asyncio.Lock())


def _unique_input_path(file_name: str, default: str) -> Path:
    safe_name = convert.safe_name(file_name, default)
    return convert.TEMP_DIR / f"{uuid.uuid4().hex}_{safe_name}"


# callback of the menu the user came from (menu_tools | admin_main_back |
# menu_make_pdf). Stored in FSM so every back/cancel/finish returns there.
def _back_to(data: dict) -> str:
    return data.get("back_to", "menu_tools")


async def _remember_back(state: FSMContext, back_to: str):
    await state.update_data(back_to=back_to)


async def cleanup_filetools_state(state: FSMContext) -> None:
    """Remove files collected during an abandoned image conversion."""
    key = state.key
    async with _flow_lock(key.user_id, key.chat_id):
        await _cleanup_filetools_state_locked(state)


async def _cleanup_filetools_state_locked(state: FSMContext) -> None:
    data = await state.get_data()
    for image_path in data.get("img_paths", []):
        Path(image_path).unlink(missing_ok=True)


@router.callback_query(F.data == "tools_cancel")
async def tools_cancel_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("conversion_phase") == "finalizing":
        await callback.answer(
            "⏳ ساخت PDF شروع شده و امکان لغو آن وجود ندارد.",
            show_alert=True,
        )
        return
    back_to = _back_to(data)
    key = state.key
    async with _flow_lock(key.user_id, key.chat_id):
        data = await state.get_data()
        if data.get("conversion_phase") == "finalizing":
            await callback.answer(
                "⏳ ساخت PDF شروع شده و امکان لغو آن وجود ندارد.",
                show_alert=True,
            )
            return
        await _cleanup_filetools_state_locked(state)
        await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "❌ عملیات لغو شد.",
        reply_markup=keyboards.file_tools_keyboard(back_to),
    )


# ─── Images → PDF ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "tool_images_pdf")
async def tool_images_pdf_start(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🖼 <b>تصاویر → PDF</b>\n\n"
        "روش تبدیل را انتخاب کنید:",
        reply_markup=keyboards.image_conversion_mode_keyboard(),
        parse_mode="HTML",
    )


async def _start_image_mode(
    callback: CallbackQuery,
    state: FSMContext,
    flow_state: State,
    prompt: str,
) -> None:
    await callback.answer()
    await cleanup_filetools_state(state)
    await state.clear()
    await state.set_state(flow_state)
    await state.update_data(
        img_paths=[],
        img_total_bytes=0,
        conversion_phase="receiving",
        back_to="menu_tools",
    )
    await callback.message.edit_text(
        prompt,
        reply_markup=keyboards.cancel_keyboard("tools_cancel"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "tool_images_single")
async def tool_images_single_start(callback: CallbackQuery, state: FSMContext):
    await _start_image_mode(
        callback,
        state,
        FileToolsFlow.waiting_single_image,
        "🖼️ یک تصویر ارسال کنید تا به PDF تبدیلش کنم:",
    )


@router.callback_query(F.data == "tool_images_multi")
async def tool_images_multi_start(callback: CallbackQuery, state: FSMContext):
    await _start_image_mode(
        callback,
        state,
        FileToolsFlow.waiting_images,
        "تصاویرت رو به ترتیب موردنظرت ارسال کن. بعد از ارسال همه تصاویر، "
        "کلمه pdfs رو بفرست تا فایل PDF ساخته بشه.",
    )


def _image_file(message: Message) -> tuple[PhotoSize | Document, str] | None:
    if message.photo:
        photo = message.photo[-1]
        return photo, ".jpg"
    document = message.document
    if document and (document.mime_type or "").lower().startswith("image/"):
        suffix = Path(document.file_name or "").suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
            suffix = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/bmp": ".bmp",
                "image/tiff": ".tiff",
            }.get((document.mime_type or "").lower(), "")
        return document, suffix
    return None


class _ImageDimensionsExceeded(ValueError):
    pass


def _validate_downloaded_image(path: Path) -> int:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as image:
            if image.width <= 0 or image.height <= 0:
                raise ValueError("ابعاد تصویر معتبر نیست.")
            pixel_count = image.width * image.height
            if pixel_count > MAX_IMAGE_PIXELS:
                raise _ImageDimensionsExceeded(
                    "ابعاد تصویر از حد مجاز پردازش بیشتر است."
                )
            image.verify()
        with Image.open(path) as image:
            image.load()
            return pixel_count
    except _ImageDimensionsExceeded:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("فایل تصویر خراب یا پشتیبانی‌نشده است.") from exc


async def _download_image(
    message: Message, image: PhotoSize | Document
) -> tuple[Path, int]:
    reported_size = getattr(image, "file_size", None)
    if reported_size is not None and reported_size > MAX_IMAGE_BYTES:
        raise ValueError("حجم هر تصویر باید حداکثر ۲۰ مگابایت باشد.")

    destination = Path(convert.TEMP_DIR) / f"{uuid.uuid4().hex}.image"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        await message.bot.download(image, destination=destination)
        actual_size = destination.stat().st_size
        if actual_size <= 0:
            raise ValueError("فایل تصویر خالی است.")
        if actual_size > MAX_IMAGE_BYTES:
            raise ValueError("حجم هر تصویر باید حداکثر ۲۰ مگابایت باشد.")
        pixel_count = _validate_downloaded_image(destination)
        return destination, pixel_count
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


async def _finish_image_pdf(
    message: Message,
    state: FSMContext,
    image_paths: list[str],
    back_to: str,
) -> None:
    output = Path(convert.TEMP_DIR) / f"{uuid.uuid4().hex}.pdf"
    key = state.key
    async with _flow_lock(key.user_id, key.chat_id):
        data = await state.get_data()
        if (
            await state.get_state() != FileToolsFlow.finalizing_images.state
            or data.get("img_paths") != image_paths
        ):
            return
        try:
            await message.answer("⏳ در حال ساخت PDF...")
            convert.images_to_pdf([Path(path) for path in image_paths], output)
            if output.stat().st_size > MAX_OUTPUT_PDF_BYTES:
                raise ValueError("حجم PDF از حد مجاز تلگرام بیشتر شد.")
            await message.answer_document(
                FSInputFile(output), caption="📄 فایل PDF آماده شد ✅")
            try:
                await models.add_convert_job(
                    message.from_user.id,
                    "images",
                    "pdf",
                    output_type=output.name,
                )
            except Exception as exc:
                logger.warning(
                    f"Could not record image-to-PDF job for user "
                    f"{message.from_user.id}: {exc}"
                )
            await message.answer(
                "🛠 گزینه دیگری لازم دارید؟",
                reply_markup=keyboards.file_tools_keyboard(back_to),
            )
        except Exception as exc:
            logger.exception(
                f"Image-to-PDF failed for user {message.from_user.id}: {exc}"
            )
            await message.answer(
                "❌ ساخت یا ارسال PDF ناموفق بود. لطفاً دوباره تلاش کنید.",
                reply_markup=keyboards.file_tools_keyboard(back_to),
            )
        finally:
            output.unlink(missing_ok=True)
            await _cleanup_filetools_state_locked(state)
            await state.clear()


async def _handle_image_input(message: Message, state: FSMContext, single: bool) -> None:
    key = state.key
    single_job: tuple[list[str], str] | None = None
    async with _flow_lock(key.user_id, key.chat_id):
        current_state = await state.get_state()
        expected = (
            FileToolsFlow.waiting_single_image.state
            if single
            else FileToolsFlow.waiting_images.state
        )
        if current_state != expected:
            if current_state == FileToolsFlow.finalizing_images.state:
                await message.answer("⏳ ساخت PDF در حال انجام است؛ لطفاً صبر کنید.")
            return

        image_info = _image_file(message)
        if image_info is None:
            await message.answer("❌ لطفاً یک تصویر معتبر ارسال کنید.")
            return
        image, _ = image_info

        if single:
            paths: list[str] = []
        else:
            data = await state.get_data()
            paths = list(data.get("img_paths", []))
            if len(paths) >= MAX_IMAGES_PER_PDF:
                await message.answer(
                    f"❌ حداکثر می‌توانید {MAX_IMAGES_PER_PDF} تصویر در یک PDF قرار دهید."
                )
                return

        try:
            path, pixel_count = await _download_image(message, image)
        except ValueError as exc:
            await message.answer(f"❌ {exc}")
            return
        except Exception as exc:
            logger.warning(
                f"Image download failed for user {message.from_user.id}: {exc}"
            )
            await message.answer("❌ دریافت تصویر ناموفق بود. دوباره تلاش کنید.")
            return

        if single:
            paths = [str(path)]
            await state.set_state(FileToolsFlow.finalizing_images)
            await state.update_data(
                img_paths=paths,
                conversion_phase="finalizing",
                back_to=_back_to(await state.get_data()),
            )
            back_to = _back_to(await state.get_data())
            single_job = (paths, back_to)
        else:
            data = await state.get_data()
            total_size = int(data.get("img_total_bytes", 0)) + path.stat().st_size
            if total_size > MAX_TOTAL_IMAGE_BYTES:
                path.unlink(missing_ok=True)
                await message.answer(
                    "❌ مجموع حجم تصاویر نباید بیشتر از ۴۵ مگابایت باشد."
                )
                return
            total_pixels = int(data.get("img_total_pixels", 0)) + pixel_count
            if total_pixels > MAX_TOTAL_IMAGE_PIXELS:
                path.unlink(missing_ok=True)
                await message.answer(
                    "❌ مجموع ابعاد تصاویر از حد مجاز پردازش بیشتر است."
                )
                return

            paths.append(str(path))
            await state.update_data(
                img_paths=paths,
                img_total_bytes=total_size,
                img_total_pixels=total_pixels,
            )
            await message.answer(
                f"✅ تصویر شماره {len(paths)} ذخیره شد. "
                "برای افزودن تصاویر بیشتر، ارسال را ادامه بده. "
                "برای ساخت PDF، کلمه pdfs را بفرست."
            )

    if single_job is not None:
        await _finish_image_pdf(message, state, single_job[0], single_job[1])


@router.message(StateFilter(FileToolsFlow.waiting_single_image))
async def tool_images_single_receive(message: Message, state: FSMContext):
    await _handle_image_input(message, state, single=True)


@router.message(StateFilter(FileToolsFlow.waiting_images), F.photo | F.document)
async def tool_images_multi_receive(message: Message, state: FSMContext):
    await _handle_image_input(message, state, single=False)


@router.message(StateFilter(FileToolsFlow.waiting_images), F.text)
async def tool_images_multi_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text.casefold() != "pdfs":
        await message.answer(
            "برای افزودن تصویر، عکس بفرستید؛ برای ساخت PDF، کلمه pdfs را ارسال کنید."
        )
        return

    key = state.key
    async with _flow_lock(key.user_id, key.chat_id):
        if await state.get_state() != FileToolsFlow.waiting_images.state:
            await message.answer("⏳ این فرایند قبلاً شروع به نهایی‌سازی کرده است.")
            return
        data = await state.get_data()
        paths = list(data.get("img_paths", []))
        if not paths:
            await message.answer("❌ هنوز تصویری دریافت نشده است؛ ابتدا عکس بفرستید.")
            return
        await state.set_state(FileToolsFlow.finalizing_images)
        await state.update_data(conversion_phase="finalizing")
        back_to = _back_to(data)

    await _finish_image_pdf(message, state, paths, back_to)


@router.message(StateFilter(FileToolsFlow.finalizing_images))
async def tool_images_finalizing_message(message: Message):
    await message.answer("⏳ ساخت PDF در حال انجام است؛ لطفاً صبر کنید.")


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
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = _unique_input_path(doc.file_name or "file", "file")
    back_to = _back_to(await state.get_data())
    try:
        await message.bot.download(doc, destination=src)
    except Exception as e:
        src.unlink(missing_ok=True)
        logger.warning(f"Word download failed for user {message.from_user.id}: {e}")
        await message.answer("❌ دریافت فایل ناموفق بود. دوباره ارسال کنید:")
        return
    await state.clear()
    try:
        out_pdf = convert.word_to_pdf(src, dest_dir)
    except Exception as e:
        await message.answer(f"❌ {e}", reply_markup=keyboards.file_tools_keyboard(back_to))
        src.unlink(missing_ok=True)
        (dest_dir / f"{src.stem}.pdf").unlink(missing_ok=True)
        return
    try:
        await message.answer_document(
            FSInputFile(out_pdf), caption="✅ فایل PDF آماده شد")
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
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = _unique_input_path(doc.file_name or "file", "file")
    back_to = _back_to(await state.get_data())
    try:
        await message.bot.download(doc, destination=src)
    except Exception as e:
        src.unlink(missing_ok=True)
        logger.warning(f"PDF download failed for user {message.from_user.id}: {e}")
        await message.answer("❌ دریافت فایل ناموفق بود. دوباره ارسال کنید:")
        return
    await state.clear()
    out = dest_dir / (src.stem + ".docx")
    try:
        convert.pdf_to_word(src, out)
    except Exception as e:
        await message.answer(f"❌ خطا در تبدیل: {e}", reply_markup=keyboards.file_tools_keyboard(back_to))
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        return
    try:
        await message.answer_document(
            FSInputFile(out), caption="✅ فایل Word آماده شد")
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
