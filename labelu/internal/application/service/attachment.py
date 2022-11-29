import aiofiles
import os
import shutil
import uuid
from typing import List, Tuple
from pathlib import Path

from loguru import logger
from fastapi import status
from sqlalchemy.orm import Session

from labelu.internal.common.config import settings
from labelu.internal.common.error_code import ErrorCode
from labelu.internal.common.error_code import UnicornException
from labelu.internal.domain.models.user import User
from labelu.internal.domain.models.task import TaskStatus
from labelu.internal.domain.models.attachment import TaskAttachment
from labelu.internal.adapter.persistence import crud_task
from labelu.internal.adapter.persistence import crud_attachment
from labelu.internal.application.command.attachment import AttachmentCommand
from labelu.internal.application.command.attachment import AttachmentDeleteCommand
from labelu.internal.application.response.base import CommonDataResp
from labelu.internal.application.response.attachment import AttachmentResponse


async def create(
    db: Session, task_id: int, cmd: AttachmentCommand, current_user: User
) -> AttachmentResponse:

    # check task not finished
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        raise UnicornException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUN,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if task.status == TaskStatus.FINISHED:
        raise UnicornException(
            code=ErrorCode.CODE_50001_TASK_FINISHED_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # save file
    try:
        # file relative path
        attachment_relative_base_dir = Path(settings.UPLOAD_DIR).joinpath(
            str(task_id), cmd.path.strip()
        )
        attachment_relative_path = str(
            attachment_relative_base_dir.joinpath(
                str(uuid.uuid4())[0:8] + "-" + cmd.file.filename
            )
        )

        # file full path
        attachment_full_base_dir = Path(settings.MEDIA_ROOT).joinpath(
            attachment_relative_base_dir
        )
        attachment_full_path = Path(settings.MEDIA_ROOT).joinpath(
            attachment_relative_path
        )

        # create dicreatory
        attachment_full_base_dir.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(attachment_full_path, "wb") as out_file:
            content = await cmd.file.read()  # async read
            await out_file.write(content)  # async write
    except:
        raise UnicornException(
            code=ErrorCode.CODE_51000_CREATE_ATTACHMENT_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # check file already saved
    attachment_status = False
    if attachment_full_path.exists():
        attachment_status = True
    # add a task file record
    attachment_id = 0
    try:
        attachment = crud_attachment.create(
            db=db,
            attachment=TaskAttachment(
                path=attachment_relative_path,
                created_by=current_user.id,
                updated_by=current_user.id,
                task_id=task_id,
                status=attachment_status,
            ),
        )
        attachment_id = attachment.id
    except Exception as e:
        attachment_status = False
        logger.error(e)
    # response
    return AttachmentResponse(
        id=attachment_id,
        url=f"{settings.HOST}:{settings.PORT}/tasks/{task_id}/attachments/{attachment_id}",
        status=attachment_status,
    )


async def download_attachment(
    db: Session, task_id: int, attachment_id: int, current_user: User
) -> str:

    # get file path
    task_file = crud_attachment.get(db=db, attachment_id=attachment_id)
    if not task_file:
        raise UnicornException(
            code=ErrorCode.CODE_51001_TASK_ATTACHMENT_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # response
    return Path(settings.MEDIA_ROOT, f"{task_file.path}")


async def delete(
    db: Session, task_id: int, cmd: AttachmentDeleteCommand, current_user: User
) -> CommonDataResp:

    # get task
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        raise UnicornException(
            code=ErrorCode.CODE_51001_TASK_ATTACHMENT_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if task.created_by != current_user.id:
        raise UnicornException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # delete media
    try:
        attachments = crud_attachment.get_by_ids(
            db=db, attachment_ids=cmd.attachment_ids
        )
        for attachment in attachments:
            file_full_path = Path(settings.MEDIA_ROOT).joinpath(attachment.path)
            os.remove(file_full_path)
    except Exception as e:
        logger.error(e)

    # delete
    crud_attachment.delete(db=db, attachment_ids=cmd.attachment_ids)

    # response
    return CommonDataResp(ok=True)