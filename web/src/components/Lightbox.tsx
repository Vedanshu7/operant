import { useEffect, type ReactElement } from "react";

export interface LightboxProps {
  src: string | null;
  alt: string;
  onClose: () => void;
}

export function Lightbox({ src, alt, onClose }: LightboxProps): ReactElement | null {
  useEffect(() => {
    if (!src) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [src, onClose]);

  if (!src) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={alt}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6"
      onClick={onClose}
    >
      <img src={src} alt={alt} className="max-h-full max-w-full rounded shadow-2xl" />
    </div>
  );
}
