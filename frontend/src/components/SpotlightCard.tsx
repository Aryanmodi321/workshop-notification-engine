import { useRef, type MouseEvent, type ReactNode } from 'react';
import './SpotlightCard.css';

type SpotlightCardProps = {
  children: ReactNode;
  className?: string;
  spotlightColor?: string;
};

export default function SpotlightCard({
  children,
  className = '',
  spotlightColor = 'rgba(255, 255, 255, 0.25)',
}: SpotlightCardProps) {
  const cardRef = useRef<HTMLDivElement>(null);

  const handleMouseMove = (event: MouseEvent<HTMLDivElement>) => {
    const card = cardRef.current;
    if (!card) return;
    const bounds = card.getBoundingClientRect();
    card.style.setProperty('--mouse-x', `${event.clientX - bounds.left}px`);
    card.style.setProperty('--mouse-y', `${event.clientY - bounds.top}px`);
    card.style.setProperty('--spotlight-color', spotlightColor);
  };

  return (
    <div ref={cardRef} onMouseMove={handleMouseMove} className={`card-spotlight ${className}`}>
      {children}
    </div>
  );
}
