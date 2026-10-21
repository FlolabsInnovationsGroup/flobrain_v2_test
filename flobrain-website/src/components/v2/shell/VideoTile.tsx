"use client";

import { Video, VideoOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";

/**
 * The optional video/self tile from the cockpit layout (``panels.video``): a camera preview to
 * check how you look and sound before a call. The camera turns on only when you press the button,
 * and turns off when you press it again or leave the page. Never shown in low-bandwidth mode.
 */
export function VideoTile() {
  const tr = useTr();
  const video = useRef<HTMLVideoElement>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const el = video.current;
    if (el) el.srcObject = stream;
    return () => stream?.getTracks().forEach((t) => t.stop());
  }, [stream]);

  async function toggle() {
    setError("");
    if (stream) {
      setStream(null);
      return;
    }
    try {
      setStream(await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 180 }, audio: false }));
    } catch {
      setError(tr("The browser did not give access to the camera."));
    }
  }

  return (
    <div className="px-3 pb-3">
      <p className="mb-1 px-2 text-xs font-medium text-[color:var(--fb-v2-text-muted)]">{tr("Camera")}</p>
      <div className="overflow-hidden rounded-lg bg-black/40">
        {stream ? (
          <video ref={video} autoPlay muted playsInline className="aspect-video w-full -scale-x-100 object-cover" aria-label={tr("Your camera preview")} />
        ) : (
          <div className="flex aspect-video items-center justify-center text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Camera is off")}</div>
        )}
      </div>
      <Button variant="ghost" className="mt-1 w-full gap-2" onClick={toggle}>
        {stream ? <VideoOff size={16} aria-hidden /> : <Video size={16} aria-hidden />}
        {stream ? tr("Turn camera off") : tr("Check my camera")}
      </Button>
      {error ? <p className="px-2 text-xs text-[color:var(--fb-v2-error)]">{error}</p> : null}
    </div>
  );
}
