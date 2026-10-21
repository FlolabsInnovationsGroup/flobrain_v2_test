from django.core.management.base import BaseCommand

from content_studio import demo_media


class Command(BaseCommand):
    help = "Rebuild the bundled Content Studio demo media (sample renders, recording, voiceover) with FFmpeg."

    def add_arguments(self, parser):
        parser.add_argument("--ffmpeg", default="/usr/bin/ffmpeg")
        parser.add_argument("--ffprobe", default="/usr/bin/ffprobe")

    def handle(self, *args, **options):
        data = demo_media.build(options["ffmpeg"], options["ffprobe"])
        self.stdout.write(f"built {demo_media.HERE}: {data}")
