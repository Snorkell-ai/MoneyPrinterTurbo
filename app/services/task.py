import math
import os.path
import re
from os import path

from edge_tts import SubMaker
from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import llm, material, subtitle, video, voice
from app.services import state as sm
from app.utils import utils


def generate_script(task_id, params):
    """Generate a video script based on provided parameters.

    This function attempts to generate a video script using the provided
    parameters. If a video script is already provided in the parameters, it
    will be stripped of leading and trailing whitespace and logged for
    debugging purposes. If no script is provided, it will call an external
    language model to generate the script based on the subject, language,
    and number of paragraphs specified in the parameters. If the script
    generation fails, the task state is updated to failed, and an error
    message is logged.

    Args:
        task_id (str): The identifier for the task being processed.
        params (object): An object containing parameters for script generation,
            including video_script, video_subject, video_language,
            and paragraph_number.

    Returns:
        str or None: The generated video script if successful; otherwise, None.
    """

    logger.info("\n\n## generating video script")
    video_script = params.video_script.strip()
    if not video_script:
        video_script = llm.generate_script(
            video_subject=params.video_subject,
            language=params.video_language,
            paragraph_number=params.paragraph_number,
        )
    else:
        logger.debug(f"video script: \n{video_script}")

    if not video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video script.")
        return None

    return video_script


def generate_terms(task_id, params, video_script):
    """Generate video terms based on provided parameters.

    This function generates a list of video terms either from the provided
    `video_terms` in the `params` object or by calling an external language
    model (LLM) to generate terms based on the `video_subject` and
    `video_script`. If `video_terms` is provided as a string, it is split
    into a list. If it is an empty list after processing, the task state is
    updated to failed.

    Args:
        task_id (str): The identifier for the task being processed.
        params (object): An object containing parameters including
            `video_terms` and `video_subject`.
        video_script (str): The script for the video which may be
            used to generate terms.

    Returns:
        list: A list of generated or provided video terms.

    Raises:
        ValueError: If `video_terms` is neither a string nor a list
            of strings.
    """

    logger.info("\n\n## generating video terms")
    video_terms = params.video_terms
    if not video_terms:
        video_terms = llm.generate_terms(
            video_subject=params.video_subject, video_script=video_script, amount=5
        )
    else:
        if isinstance(video_terms, str):
            video_terms = [term.strip() for term in re.split(r"[,，]", video_terms)]
        elif isinstance(video_terms, list):
            video_terms = [term.strip() for term in video_terms]
        else:
            raise ValueError("video_terms must be a string or a list of strings.")

        logger.debug(f"video terms: {utils.to_json(video_terms)}")

    if not video_terms:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video terms.")
        return None

    return video_terms


def save_script_data(task_id, video_script, video_terms, params):
    """Save video script data to a JSON file.

    This function creates a JSON file containing the video script, search
    terms, and additional parameters associated with a specific task. The
    JSON file is saved in the task directory, which is determined by the
    provided task ID.

    Args:
        task_id (str): The identifier for the task.
        video_script (str): The video script to be saved.
        video_terms (list): A list of search terms related to the video.
        params (dict): Additional parameters to be included in the script data.
    """

    script_file = path.join(utils.task_dir(task_id), "script.json")
    script_data = {
        "script": video_script,
        "search_terms": video_terms,
        "params": params,
    }

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(utils.to_json(script_data))


def generate_audio(task_id, params, video_script):
    """Generate audio from a video script using text-to-speech.

    This function generates an audio file from the provided video script
    using a text-to-speech service. It logs the process and checks for
    potential issues such as language mismatches or network availability. If
    the audio generation fails, it updates the task state to failed and logs
    an error message with troubleshooting tips. If successful, it returns
    the path to the generated audio file, its duration, and the sub_maker
    object used for audio generation.

    Args:
        task_id (str): The identifier for the task being processed.
        params (object): An object containing parameters for voice generation,
            including voice name and rate.
        video_script (str): The script that will be converted to audio.

    Returns:
        tuple: A tuple containing:
            - str: The path to the generated audio file.
            - int: The duration of the audio in seconds.
            - object: The sub_maker object used for audio generation.
    """

    logger.info("\n\n## generating audio")
    audio_file = path.join(utils.task_dir(task_id), "audio.mp3")
    sub_maker = voice.tts(
        text=video_script,
        voice_name=voice.parse_voice_name(params.voice_name),
        voice_rate=params.voice_rate,
        voice_file=audio_file,
    )
    if sub_maker is None:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error(
            """failed to generate audio:
1. check if the language of the voice matches the language of the video script.
2. check if the network is available. If you are in China, it is recommended to use a VPN and enable the global traffic mode.
        """.strip()
        )
        return None, None, None

    audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
    return audio_file, audio_duration, sub_maker


def generate_subtitle(task_id, params, video_script, sub_maker, audio_file):
    """Generate subtitles for a video based on the provided parameters.

    This function generates subtitles for a video by utilizing a specified
    subtitle provider. It first checks if subtitles are enabled in the
    parameters. If enabled, it attempts to create subtitles using the
    designated provider (either "edge" or "whisper"). If the "edge" provider
    fails to create the subtitle file, it falls back to using the "whisper"
    provider. The generated subtitles are then corrected based on the video
    script, and the path to the subtitle file is returned.

    Args:
        task_id (str): The identifier for the task.
        params (object): An object containing parameters, including
            whether subtitles are enabled.
        video_script (str): The script of the video for reference.
        sub_maker (object): An object responsible for creating subtitles.
        audio_file (str): The path to the audio file associated with the video.

    Returns:
        str: The path to the generated subtitle file, or an empty string if
            subtitles are not enabled or if the subtitle file is invalid.
    """

    if not params.subtitle_enabled:
        return ""

    subtitle_path = path.join(utils.task_dir(task_id), "subtitle.srt")
    subtitle_provider = config.app.get("subtitle_provider", "").strip().lower()
    logger.info(f"\n\n## generating subtitle, provider: {subtitle_provider}")

    subtitle_fallback = False
    if subtitle_provider == "edge":
        voice.create_subtitle(
            text=video_script, sub_maker=sub_maker, subtitle_file=subtitle_path
        )
        if not os.path.exists(subtitle_path):
            subtitle_fallback = True
            logger.warning("subtitle file not found, fallback to whisper")

    if subtitle_provider == "whisper" or subtitle_fallback:
        subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
        logger.info("\n\n## correcting subtitle")
        subtitle.correct(subtitle_file=subtitle_path, video_script=video_script)

    subtitle_lines = subtitle.file_to_subtitles(subtitle_path)
    if not subtitle_lines:
        logger.warning(f"subtitle file is invalid: {subtitle_path}")
        return ""

    return subtitle_path


def get_video_materials(task_id, params, video_terms, audio_duration):
    """Retrieve video materials based on the specified parameters.

    This function processes video materials either from a local source or by
    downloading them from a specified video source. If the video source is
    local, it preprocesses the provided materials and returns their URLs. If
    the source is remote, it attempts to download videos based on the
    provided search terms and parameters. In case of failure to find valid
    materials or download videos, it updates the task state to failed and
    logs an error message.

    Args:
        task_id (str): The identifier for the task being processed.
        params (object): An object containing various parameters including video source,
            materials, and durations.
        video_terms (list): A list of terms used for searching videos if downloading from a remote
            source.
        audio_duration (int): The duration of the audio to be used in the video processing.

    Returns:
        list or None: A list of URLs of the processed video materials if
            successful, otherwise None.
    """

    if params.video_source == "local":
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        if not materials:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "no valid materials found, please check the materials and try again."
            )
            return None
        return [material_info.url for material_info in materials]
    else:
        logger.info(f"\n\n## downloading videos from {params.video_source}")
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=video_terms,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_contact_mode=params.video_concat_mode,
            audio_duration=audio_duration * params.video_count,
            max_clip_duration=params.video_clip_duration,
        )
        if not downloaded_videos:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "failed to download videos, maybe the network is not available. if you are in China, please use a VPN."
            )
            return None
        return downloaded_videos


def generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
):
    """Generate final video files from downloaded videos and audio.

    This function combines a list of downloaded videos into a single video
    file for each specified video count. It utilizes the provided audio file
    and subtitles to generate the final output videos. The progress of the
    video generation is updated throughout the process. The function returns
    the paths of the final generated videos and the combined video files.

    Args:
        task_id (str): The identifier for the current task.
        params (Params): An object containing parameters for video generation,
            including video count, aspect ratio, clip duration,
            and thread count.
        downloaded_videos (list): A list of paths to the downloaded video files.
        audio_file (str): The path to the audio file to be used in the final videos.
        subtitle_path (str): The path to the subtitle file to be included in the final videos.

    Returns:
        tuple: A tuple containing two lists:
            - list: Paths to the final generated video files.
            - list: Paths to the combined video files.
    """

    final_video_paths = []
    combined_video_paths = []
    video_concat_mode = (
        params.video_concat_mode if params.video_count == 1 else VideoConcatMode.random
    )

    _progress = 50
    for i in range(params.video_count):
        index = i + 1
        combined_video_path = path.join(
            utils.task_dir(task_id), f"combined-{index}.mp4"
        )
        logger.info(f"\n\n## combining video: {index} => {combined_video_path}")
        video.combine_videos(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=params.video_aspect,
            video_concat_mode=video_concat_mode,
            max_clip_duration=params.video_clip_duration,
            threads=params.n_threads,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_path = path.join(utils.task_dir(task_id), f"final-{index}.mp4")

        logger.info(f"\n\n## generating video: {index} => {final_video_path}")
        video.generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_path,
            output_file=final_video_path,
            params=params,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_paths.append(final_video_path)
        combined_video_paths.append(combined_video_path)

    return final_video_paths, combined_video_paths


def start(task_id, params: VideoParams, stop_at: str = "video"):
    """Start the video processing task.

    This function orchestrates the video processing workflow by generating a
    script, terms, audio, subtitles, and final videos based on the provided
    parameters. It updates the task state throughout the process and allows
    for stopping at various stages of the workflow. The function handles
    different video sources and manages progress updates to reflect the
    current state of the task.

    Args:
        task_id (str): The unique identifier for the task.
        params (VideoParams): The parameters required for video processing.
        stop_at (str?): The stage at which to stop processing.
            Can be one of "video", "script", "terms", "audio", "subtitle", or
            "materials". Defaults to "video".

    Returns:
        dict: A dictionary containing the results of the processing at the specified
            stop stage, which may include:
            - script (str): The generated video script.
            - terms (str): The generated video terms.
            - audio_file (str): The path to the generated audio file.
            - audio_duration (float): The duration of the generated audio.
            - subtitle_path (str): The path to the generated subtitle file.
            - materials (list): The list of downloaded video materials.
    """

    logger.info(f"start task: {task_id}, stop_at: {stop_at}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)
        
    # 1. Generate script
    video_script = generate_script(task_id, params)
    if not video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script}

    # 2. Generate terms
    video_terms = ""
    if params.video_source != "local":
        video_terms = generate_terms(task_id, params, video_script)
        if not video_terms:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return

    save_script_data(task_id, video_script, video_terms, params)

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": video_script, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # 3. Generate audio
    audio_file, audio_duration, sub_maker = generate_audio(task_id, params, video_script)
    if not audio_file:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=30)

    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_file,
        )
        return {"audio_file": audio_file, "audio_duration": audio_duration}

    # 4. Generate subtitle
    subtitle_path = generate_subtitle(task_id, params, video_script, sub_maker, audio_file)

    if stop_at == "subtitle":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            subtitle_path=subtitle_path,
        )
        return {"subtitle_path": subtitle_path}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)

    # 5. Get video materials
    downloaded_videos = get_video_materials(
        task_id, params, video_terms, audio_duration
    )
    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 6. Generate final videos
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
    )

    if not final_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    logger.success(
        f"task {task_id} finished, generated {len(final_video_paths)} videos."
    )

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    return kwargs


if __name__ == "__main__":
    task_id = "task_id"
    params = VideoParams(
        video_subject="金钱的作用",
        voice_name="zh-CN-XiaoyiNeural-Female",
        voice_rate=1.0,

    )
    start(task_id, params, stop_at="video")
