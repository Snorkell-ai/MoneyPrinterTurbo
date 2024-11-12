import glob
import random
from typing import List

from loguru import logger
from moviepy.editor import *
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import ImageFont

from app.models import const
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode, VideoParams
from app.utils import utils


def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    """Retrieve a background music (BGM) file based on the specified type.

    This function checks if a BGM type is provided and returns a
    corresponding music file. If a specific BGM file is given and it exists,
    that file is returned. If the BGM type is "random", it searches for all
    MP3 files in the designated song directory and randomly selects one to
    return. If no valid BGM type is provided or no files are found, an empty
    string is returned.

    Args:
        bgm_type (str): The type of BGM to retrieve. Defaults to "random".
        bgm_file (str): The specific BGM file to return if it exists. Defaults to an empty
            string.

    Returns:
        str: The path to the selected BGM file or an empty string if no valid file is
            found.
    """

    if not bgm_type:
        return ""

    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        return random.choice(files)

    return ""


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    max_clip_duration: int = 5,
    threads: int = 2,
) -> str:
    """Combine multiple video clips into a single video synchronized with an
    audio file.

    This function takes a list of video file paths and combines them into a
    single video that is synchronized with the provided audio file. The
    videos can be concatenated either sequentially or randomly, based on the
    specified mode. Each video clip is split into segments of a maximum
    duration defined by `max_clip_duration`, and the final output video is
    resized to match the specified aspect ratio. The function also handles
    audio synchronization, ensuring that the combined video matches the
    length of the audio.

    Args:
        combined_video_path (str): The file path where the combined video will be saved.
        video_paths (List[str]): A list of file paths for the video clips to be combined.
        audio_file (str): The file path for the audio file to synchronize with the video.
        video_aspect (VideoAspect?): The aspect ratio of the output video. Defaults to VideoAspect.portrait.
        video_concat_mode (VideoConcatMode?): The mode for concatenating videos (sequential or random). Defaults to
            VideoConcatMode.random.
        max_clip_duration (int?): The maximum duration for each video clip segment in seconds. Defaults to
            5.
        threads (int?): The number of threads to use for writing the video file. Defaults to 2.

    Returns:
        str: The file path of the combined video.
    """

    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"max duration of audio: {audio_duration} seconds")
    # Required duration of each clip
    req_dur = audio_duration / len(video_paths)
    req_dur = max_clip_duration
    logger.info(f"each clip will be maximum {req_dur} seconds long")
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    clips = []
    video_duration = 0

    raw_clips = []
    for video_path in video_paths:
        clip = VideoFileClip(video_path).without_audio()
        clip_duration = clip.duration
        start_time = 0

        while start_time < clip_duration:
            end_time = min(start_time + max_clip_duration, clip_duration)
            split_clip = clip.subclip(start_time, end_time)
            raw_clips.append(split_clip)
            # logger.info(f"splitting from {start_time:.2f} to {end_time:.2f}, clip duration {clip_duration:.2f}, split_clip duration {split_clip.duration:.2f}")
            start_time = end_time
            if video_concat_mode.value == VideoConcatMode.sequential.value:
                break

    # random video_paths order
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(raw_clips)

    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
    while video_duration < audio_duration:
        for clip in raw_clips:
            # Check if clip is longer than the remaining audio
            if (audio_duration - video_duration) < clip.duration:
                clip = clip.subclip(0, (audio_duration - video_duration))
            # Only shorten clips if the calculated clip length (req_dur) is shorter than the actual clip to prevent still image
            elif req_dur < clip.duration:
                clip = clip.subclip(0, req_dur)
            clip = clip.set_fps(30)

            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height

                if clip_ratio == video_ratio:
                    # 等比例缩放
                    clip = clip.resize((video_width, video_height))
                else:
                    # 等比缩放视频
                    if clip_ratio > video_ratio:
                        # 按照目标宽度等比缩放
                        scale_factor = video_width / clip_w
                    else:
                        # 按照目标高度等比缩放
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)
                    clip_resized = clip.resize(newsize=(new_width, new_height))

                    background = ColorClip(
                        size=(video_width, video_height), color=(0, 0, 0)
                    )
                    clip = CompositeVideoClip(
                        [
                            background.set_duration(clip.duration),
                            clip_resized.set_position("center"),
                        ]
                    )

                logger.info(
                    f"resizing video to {video_width} x {video_height}, clip size: {clip_w} x {clip_h}"
                )

            if clip.duration > max_clip_duration:
                clip = clip.subclip(0, max_clip_duration)

            clips.append(clip)
            video_duration += clip.duration

    video_clip = concatenate_videoclips(clips)
    video_clip = video_clip.set_fps(30)
    logger.info("writing")
    # https://github.com/harry0703/MoneyPrinterTurbo/issues/111#issuecomment-2032354030
    video_clip.write_videofile(
        filename=combined_video_path,
        threads=threads,
        logger=None,
        temp_audiofile_path=output_dir,
        audio_codec="aac",
        fps=30,
    )
    video_clip.close()
    logger.success("completed")
    return combined_video_path


def wrap_text(text, max_width, font="Arial", fontsize=60):
    """Wrap text to fit within a specified width.

    This function takes a string of text and wraps it so that each line does
    not exceed the specified maximum width. It uses a specified font and
    font size to calculate the width of the text. If the text fits within
    the maximum width, it is returned as is. If it does not fit, the text is
    split into multiple lines that fit within the specified width. The
    height of the resulting text block is also calculated based on the
    number of lines.

    Args:
        text (str): The text to be wrapped.
        max_width (int): The maximum width of each line in pixels.
        font (str?): The font type to use for rendering the text. Defaults to "Arial".
        fontsize (int?): The size of the font to use for rendering the text. Defaults to 60.

    Returns:
        tuple: A tuple containing the wrapped text as a string and the height of the
            resulting text block in pixels.
    """

    # 创建字体对象
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        """Get the size of the given text.

        This function calculates the bounding box of the provided text using the
        current font settings. It returns the width and height of the text by
        determining the difference between the left and right edges, and the top
        and bottom edges of the bounding box.

        Args:
            inner_text (str): The text for which to calculate the size.

        Returns:
            tuple: A tuple containing the width and height of the text.
        """

        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    # logger.warning(f"wrapping text, max_width: {max_width}, text_width: {width}, text: {text}")

    processed = True

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ""
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = "\n".join(_wrapped_lines_).strip()
        height = len(_wrapped_lines_) * height
        # logger.warning(f"wrapped text: {result}")
        return result, height

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ""
    for word in chars:
        _txt_ += word
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ""
    _wrapped_lines_.append(_txt_)
    result = "\n".join(_wrapped_lines_).strip()
    height = len(_wrapped_lines_) * height
    # logger.warning(f"wrapped text: {result}")
    return result, height


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
):
    """Generate a video by combining video, audio, and subtitles.

    This function takes a video file, an audio file, and optional subtitles
    to create a new video file. It handles the positioning and styling of
    subtitles, adjusts audio levels, and manages the output settings. The
    function also logs the process and handles background music if
    specified.

    Args:
        video_path (str): The path to the input video file.
        audio_path (str): The path to the input audio file.
        subtitle_path (str): The path to the subtitle file.
        output_file (str): The path where the output video file will be saved.
        params (VideoParams): An object containing various parameters for video generation, such as
            aspect ratio, font settings, volume levels, and subtitle options.
    """

    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"start, video size: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    # https://github.com/harry0703/MoneyPrinterTurbo/issues/217
    # PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'final-1.mp4.tempTEMP_MPY_wvf_snd.mp3'
    # write into the same directory as the output file
    output_dir = os.path.dirname(output_file)

    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = "STHeitiMedium.ttc"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

        logger.info(f"using font: {font_path}")

    def create_text_clip(subtitle_item):
        """Create a text clip for subtitles in a video.

        This function generates a text clip from a given subtitle item. It wraps
        the text to fit within a specified maximum width and applies various
        styling options such as font, size, color, and position. The duration of
        the clip is determined by the start and end times provided in the
        subtitle item. The function also handles positioning the text clip based
        on user-defined parameters, ensuring that it appears correctly on the
        screen.

        Args:
            subtitle_item (tuple): A tuple containing two elements:
                - A tuple with start and end times (float, float) for the subtitle.
                - A string representing the subtitle text.

        Returns:
            TextClip: A moviepy TextClip object configured with the wrapped text and specified
                properties.
        """

        phrase = subtitle_item[1]
        max_width = video_width * 0.9
        wrapped_txt, txt_height = wrap_text(
            phrase, max_width=max_width, font=font_path, fontsize=params.font_size
        )
        _clip = TextClip(
            wrapped_txt,
            font=font_path,
            fontsize=params.font_size,
            color=params.text_fore_color,
            bg_color=params.text_background_color,
            stroke_color=params.stroke_color,
            stroke_width=params.stroke_width,
            print_cmd=False,
        )
        duration = subtitle_item[0][1] - subtitle_item[0][0]
        _clip = _clip.set_start(subtitle_item[0][0])
        _clip = _clip.set_end(subtitle_item[0][1])
        _clip = _clip.set_duration(duration)
        if params.subtitle_position == "bottom":
            _clip = _clip.set_position(("center", video_height * 0.95 - _clip.h))
        elif params.subtitle_position == "top":
            _clip = _clip.set_position(("center", video_height * 0.05))
        elif params.subtitle_position == "custom":
            # 确保字幕完全在屏幕内
            margin = 10  # 额外的边距，单位为像素
            max_y = video_height - _clip.h - margin
            min_y = margin
            custom_y = (video_height - _clip.h) * (params.custom_position / 100)
            custom_y = max(min_y, min(custom_y, max_y))  # 限制 y 值在有效范围内
            _clip = _clip.set_position(("center", custom_y))
        else:  # center
            _clip = _clip.set_position(("center", "center"))
        return _clip

    video_clip = VideoFileClip(video_path)
    audio_clip = AudioFileClip(audio_path).volumex(params.voice_volume)

    if subtitle_path and os.path.exists(subtitle_path):
        sub = SubtitlesClip(subtitles=subtitle_path, encoding="utf-8")
        text_clips = []
        for item in sub.subtitles:
            clip = create_text_clip(subtitle_item=item)
            text_clips.append(clip)
        video_clip = CompositeVideoClip([video_clip, *text_clips])

    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        try:
            bgm_clip = (
                AudioFileClip(bgm_file).volumex(params.bgm_volume).audio_fadeout(3)
            )
            bgm_clip = afx.audio_loop(bgm_clip, duration=video_clip.duration)
            audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
        except Exception as e:
            logger.error(f"failed to add bgm: {str(e)}")

    video_clip = video_clip.set_audio(audio_clip)
    video_clip.write_videofile(
        output_file,
        audio_codec="aac",
        temp_audiofile_path=output_dir,
        threads=params.n_threads or 2,
        logger=None,
        fps=30,
    )
    video_clip.close()
    del video_clip
    logger.success("completed")


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    """Preprocess a list of video and image materials.

    This function iterates through a list of materials, checking each
    material's URL. If the URL is valid, it attempts to create a video clip
    from the URL. If the creation fails, it tries to create an image clip
    instead. The function checks the dimensions of the clip and logs a
    warning if the dimensions are smaller than 480 pixels. For image
    materials, it creates a zoom effect and outputs the processed video as
    an MP4 file. The processed materials are updated with the new video
    URLs.

    Args:
        materials (List[MaterialInfo]): A list of MaterialInfo objects containing URLs
            to video or image files.
        clip_duration (int?): The duration of the clips in seconds. Defaults to 4.

    Returns:
        List[MaterialInfo]: The updated list of materials with new video URLs.
    """

    for material in materials:
        if not material.url:
            continue

        ext = utils.parse_extension(material.url)
        try:
            clip = VideoFileClip(material.url)
        except Exception:
            clip = ImageClip(material.url)

        width = clip.size[0]
        height = clip.size[1]
        if width < 480 or height < 480:
            logger.warning(f"video is too small, width: {width}, height: {height}")
            continue

        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"processing image: {material.url}")
            # 创建一个图片剪辑，并设置持续时间为3秒钟
            clip = (
                ImageClip(material.url)
                .set_duration(clip_duration)
                .set_position("center")
            )
            # 使用resize方法来添加缩放效果。这里使用了lambda函数来使得缩放效果随时间变化。
            # 假设我们想要从原始大小逐渐放大到120%的大小。
            # t代表当前时间，clip.duration为视频总时长，这里是3秒。
            # 注意：1 表示100%的大小，所以1.2表示120%的大小
            zoom_clip = clip.resize(
                lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
            )

            # 如果需要，可以创建一个包含缩放剪辑的复合视频剪辑
            # （这在您想要在视频中添加其他元素时非常有用）
            final_clip = CompositeVideoClip([zoom_clip])

            # 输出视频
            video_file = f"{material.url}.mp4"
            final_clip.write_videofile(video_file, fps=30, logger=None)
            final_clip.close()
            del final_clip
            material.url = video_file
            logger.success(f"completed: {video_file}")
    return materials


if __name__ == "__main__":
    m = MaterialInfo()
    m.url = "/Users/harry/Downloads/IMG_2915.JPG"
    m.provider = "local"
    materials = preprocess_video([m], clip_duration=4)
    print(materials)

    # txt_en = "Here's your guide to travel hacks for budget-friendly adventures"
    # txt_zh = "测试长字段这是您的旅行技巧指南帮助您进行预算友好的冒险"
    # font = utils.resource_dir() + "/fonts/STHeitiMedium.ttc"
    # for txt in [txt_en, txt_zh]:
    #     t, h = wrap_text(text=txt, max_width=1000, font=font, fontsize=60)
    #     print(t)
    #
    # task_id = "aa563149-a7ea-49c2-b39f-8c32cc225baf"
    # task_dir = utils.task_dir(task_id)
    # video_file = f"{task_dir}/combined-1.mp4"
    # audio_file = f"{task_dir}/audio.mp3"
    # subtitle_file = f"{task_dir}/subtitle.srt"
    # output_file = f"{task_dir}/final.mp4"
    #
    # # video_paths = []
    # # for file in os.listdir(utils.storage_dir("test")):
    # #     if file.endswith(".mp4"):
    # #         video_paths.append(os.path.join(utils.storage_dir("test"), file))
    # #
    # # combine_videos(combined_video_path=video_file,
    # #                audio_file=audio_file,
    # #                video_paths=video_paths,
    # #                video_aspect=VideoAspect.portrait,
    # #                video_concat_mode=VideoConcatMode.random,
    # #                max_clip_duration=5,
    # #                threads=2)
    #
    # cfg = VideoParams()
    # cfg.video_aspect = VideoAspect.portrait
    # cfg.font_name = "STHeitiMedium.ttc"
    # cfg.font_size = 60
    # cfg.stroke_color = "#000000"
    # cfg.stroke_width = 1.5
    # cfg.text_fore_color = "#FFFFFF"
    # cfg.text_background_color = "transparent"
    # cfg.bgm_type = "random"
    # cfg.bgm_file = ""
    # cfg.bgm_volume = 1.0
    # cfg.subtitle_enabled = True
    # cfg.subtitle_position = "bottom"
    # cfg.n_threads = 2
    # cfg.paragraph_number = 1
    #
    # cfg.voice_volume = 1.0
    #
    # generate_video(video_path=video_file,
    #                audio_path=audio_file,
    #                subtitle_path=subtitle_file,
    #                output_file=output_file,
    #                params=cfg
    #                )
