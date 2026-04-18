import { Card } from '@/components/ui/card';
import { cn } from '@/utils';
import { PlayIcon, PauseIcon, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAudio } from '@/hooks/useDashboard';
import { useRef, useState, useCallback, useEffect, useMemo } from 'react';

interface PodcastPlayerProps {
  audioDate?: string;
  className?: string;
}

const BAR_COUNT = 48;

function generateBarHeights(seed: number): number[] {
  const heights: number[] = [];
  let state = seed || 7;
  for (let i = 0; i < BAR_COUNT; i++) {
    state = ((state * 16807) + 0) % 2147483647;
    const raw = (state & 0xffff) / 0xffff;
    const envelope = Math.sin((i / BAR_COUNT) * Math.PI);
    const jitter = 0.15 + raw * 0.85;
    heights.push(Math.max(0.08, jitter * (0.3 + envelope * 0.7)));
  }
  return heights;
}

function formatTime(time: number): string {
  const minutes = Math.floor(time / 60);
  const seconds = Math.floor(time % 60);
  return `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`;
}

export default function PodcastPlayer({ audioDate, className }: PodcastPlayerProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isBuffering, setIsBuffering] = useState(false);
  const [isAudioReady, setIsAudioReady] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const waveformRef = useRef<HTMLDivElement | null>(null);

  const {
    data: audioData,
    isLoading,
    error,
  } = useAudio(audioDate);

  const barHeights = useMemo(
    () => generateBarHeights(audioDate ? parseInt(audioDate.slice(-5).replace(/-/g, ''), 10) : 7),
    [audioDate],
  );

  const progress = duration > 0 ? currentTime / duration : 0;

  useEffect(() => {
    if (!audioRef.current || !audioData?.url) return;
    const apiBaseUrl = import.meta.env.API_BASE_URL || '';
    const absoluteUrl = audioData.url.startsWith('/')
      ? `${apiBaseUrl}${audioData.url}`
      : audioData.url;
    audioRef.current.src = absoluteUrl;
    audioRef.current.load();
    setIsPlaying(false); // eslint-disable-line react-hooks/set-state-in-effect -- reset player state on source change
    setIsBuffering(false);
    setIsAudioReady(false);
    setCurrentTime(0);
    setDuration(0);
  }, [audioData?.url]);

  const togglePlayPause = useCallback(() => {
    if (!audioRef.current) return;
    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play()
        .then(() => setIsPlaying(true))
        .catch(() => setIsPlaying(false));
    }
  }, [isPlaying]);

  const handleTimeUpdate = useCallback(() => {
    if (audioRef.current) setCurrentTime(audioRef.current.currentTime);
  }, []);

  const handleLoadedMetadata = useCallback(() => {
    if (audioRef.current) setDuration(audioRef.current.duration);
  }, []);

  const handleEnded = useCallback(() => setIsPlaying(false), []);
  const handleAudioError = useCallback(() => { setIsPlaying(false); setIsBuffering(false); }, []);
  const handleWaiting = useCallback(() => {
    if (isPlaying) setIsBuffering(true);
  }, [isPlaying]);
  const handleCanPlay = useCallback(() => { setIsBuffering(false); setIsAudioReady(true); }, []);

  const handleWaveformClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!audioRef.current || !duration || !waveformRef.current) return;
      const rect = waveformRef.current.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const newTime = ratio * duration;
      audioRef.current.currentTime = newTime;
      setCurrentTime(newTime);
    },
    [duration],
  );

  const hasAudio = !error && !isLoading && audioData?.url;

  return (
    <Card className={cn('flex flex-col h-full min-h-[200px] overflow-hidden', className)}>
      <div className="flex flex-col h-full px-6 py-5 gap-3">
        <audio
          ref={audioRef}
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={handleLoadedMetadata}
          onEnded={handleEnded}
          onError={handleAudioError}
          onWaiting={handleWaiting}
          onCanPlay={handleCanPlay}
          preload="auto"
        />

        {/* Header */}
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Compass Bulletin
        </span>

        {/* Center: play + waveform */}
        <div className="flex-1 flex items-center gap-4">
          <Button
            variant="outline"
            size="icon"
            className="h-11 w-11 rounded-full shrink-0"
            onClick={togglePlayPause}
            disabled={isLoading || !hasAudio}
            aria-label={isPlaying ? 'Pause audio' : 'Play audio'}
          >
            {isLoading || isBuffering || (hasAudio && !isAudioReady) ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : isPlaying ? (
              <PauseIcon className="h-5 w-5" />
            ) : (
              <PlayIcon className="h-5 w-5 ml-0.5" />
            )}
          </Button>

          {hasAudio ? (
            <div
              ref={waveformRef}
              className="flex-1 flex items-center gap-[2px] h-12 cursor-pointer"
              onClick={handleWaveformClick}
              role="progressbar"
              aria-label="Audio progress"
              aria-valuemin={0}
              aria-valuemax={duration || 100}
              aria-valuenow={currentTime}
              aria-valuetext={formatTime(currentTime)}
            >
              {barHeights.map((height, i) => {
                const barProgress = (i + 0.5) / BAR_COUNT;
                const isActive = barProgress <= progress;

                return (
                  <div
                    key={i}
                    className={cn(
                      'flex-1 min-w-[2px] rounded-full transition-colors duration-100',
                      isActive
                        ? 'bg-foreground'
                        : 'bg-muted-foreground/20',
                    )}
                    style={{ height: `${height * 100}%` }}
                  />
                );
              })}
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center h-12">
              <span className="text-muted-foreground/60 text-[11px]">
                {isLoading ? 'Chargement...' : 'Aucun bulletin disponible'}
              </span>
            </div>
          )}
        </div>

        {/* Bottom: time */}
        <div className="flex items-center justify-between">
          <span className="text-[11px] tabular-nums text-muted-foreground">
            {hasAudio ? formatTime(currentTime) : ''}
          </span>
          <span className="text-[11px] tabular-nums text-muted-foreground">
            {hasAudio && duration > 0 ? formatTime(duration) : ''}
          </span>
        </div>
      </div>
    </Card>
  );
}
