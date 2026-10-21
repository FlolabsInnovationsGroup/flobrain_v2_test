"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";

/** The ZATCA QR: the Base64 TLV text itself is what the code carries (scanned by the VAT app). */
export function QrImage({ value, size = 168, label }: { value: string; size?: number; label: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    QRCode.toDataURL(value, { margin: 1, width: size, errorCorrectionLevel: "M" })
      .then((url) => alive && setSrc(url))
      .catch(() => alive && setSrc(null));
    return () => {
      alive = false;
    };
  }, [value, size]);
  if (!src) return null;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} width={size} height={size} alt={label} className="rounded-md bg-white p-1" />;
}
