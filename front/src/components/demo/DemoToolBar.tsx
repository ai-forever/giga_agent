import React, { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { TIME_TO_NEXT_TASK } from "../../config.ts";

interface DemoToolBarProps {
  /** Когда этот проп ставится в true, запускается прогресс-обводка и таймер авто-продолжения */
  isFinished: boolean;
  onContinue: () => void;
}

const DemoToolBar: React.FC<DemoToolBarProps> = ({
  isFinished,
  onContinue,
}) => {
  const [paused, setPaused] = useState(false);
  const [showProgress, setShowProgress] = useState(false);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    const active = isFinished && !paused;
    setShowProgress(active);
    if (active) {
      timerRef.current = setTimeout(() => {
        onContinue();
      }, TIME_TO_NEXT_TASK * 1000);
    }
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [isFinished, paused, onContinue]);

  const handlePauseClick = () => {
    setPaused((val) => !val);
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const circleTotal = 125.6;
  const circleStyle: React.CSSProperties = {
    transition: `stroke-dashoffset ${TIME_TO_NEXT_TASK}s linear`,
    strokeDasharray: circleTotal,
    strokeDashoffset: showProgress ? 0 : circleTotal,
  };

  return (
    <div className="fixed bottom-5 right-5 flex flex-col print:hidden max-[900px]:bottom-1/2 max-[900px]:translate-y-1/2">
      <div
        onClick={handlePauseClick}
        className={`relative box-border rounded-[40px] mt-[10px] flex items-center justify-center w-[45px] h-[45px] cursor-pointer bg-card text-foreground ${paused ? "border-2 border-foreground" : ""}`}
      >
        <Pause size={22} />
      </div>
      <div
        onClick={onContinue}
        className="relative box-border rounded-[40px] mt-[10px] flex items-center justify-center w-[45px] h-[45px] cursor-pointer bg-card text-foreground"
      >
        {isFinished && (
          <svg
            viewBox="0 0 45 45"
            className="absolute inset-0 w-[45px] h-[45px] -rotate-90"
          >
            <circle
              cx={22.5}
              cy={22.5}
              r={20}
              fill="transparent"
              stroke="currentColor"
              strokeWidth={2}
              style={circleStyle}
            />
          </svg>
        )}
        <Play size={24} />
      </div>
    </div>
  );
};

export default DemoToolBar;
