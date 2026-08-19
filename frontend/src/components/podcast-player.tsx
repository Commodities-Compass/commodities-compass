import { PlayIcon, PauseIcon, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAudio } from '@/hooks/useDashboard';
import { useRef, useState, useCallback, useEffect, useMemo } from 'react';
import SectionHeader from '@/components/section-header';

interface PodcastPlayerProps {
  audioDate?: string;
  className?: string;
}

const BAR_COUNT = 56;

function generateBarHeights(seed: number): number[] {
  const heights: number[] = [];
  let state = seed || 7;
  for (let i = 0; i < BAR_COUNT; i++) {
    state = (state * 16807) % 2147483647;
    const raw = (state & 0xffff) / 0xffff;
    const envelope = Math.sin((i / BAR_COUNT) * Math.PI);
    const jitter = 0.2 + raw * 0.8;
    heights.push(Math.max(0.08, jitter * (0.35 + envelope * 0.65)));
  }
  return heights;
}

function formatTime(time: number): string {
  const minutes = Math.floor(time / 60);
  const seconds = Math.floor(time % 60);
  return `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`;
}

export default function PodcastPlayer({
  audioDate,
  className,
}: PodcastPlayerProps) {
  const { t } = useTranslation();
  const [isPlaying, setIsPlaying] = useState(false);
  const [isBuffering, setIsBuffering] = useState(false);
  const [isAudioReady, setIsAudioReady] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const waveformRef = useRef<HTMLDivElement | null>(null);

  const { data: audioData, isLoading, error } = useAudio(audioDate);

  const barHeights = useMemo(
    () =>
      generateBarHeights(
        audioDate ? parseInt(audioDate.slice(-5).replace(/-/g, ''), 10) : 7
      ),
    [audioDate]
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
    setIsPlaying(false); // eslint-disable-line react-hooks/set-state-in-effect -- reset on source change
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
      audioRef.current
        .play()
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
  const handleAudioError = useCallback(() => {
    setIsPlaying(false);
    setIsBuffering(false);
  }, []);
  const handleWaiting = useCallback(() => {
    if (isPlaying) setIsBuffering(true);
  }, [isPlaying]);
  const handleCanPlay = useCallback(() => {
    setIsBuffering(false);
    setIsAudioReady(true);
  }, []);

  const handleWaveformClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!audioRef.current || !duration || !waveformRef.current) return;
      const rect = waveformRef.current.getBoundingClientRect();
      const ratio = Math.max(
        0,
        Math.min(1, (e.clientX - rect.left) / rect.width)
      );
      const newTime = ratio * duration;
      audioRef.current.currentTime = newTime;
      setCurrentTime(newTime);
    },
    [duration]
  );

  const hasAudio = !error && !isLoading && audioData?.url;

  return (
    <section className={className} style={{ padding: '24px 0' }}>
      <style>{`
        .podcast-play-btn:not(:disabled):hover { background: var(--paper-off) !important; }
      `}</style>
      <SectionHeader numeral="I" title={t('sections.brief')} />

      <div
        style={{
          border: '1px solid var(--ink)',
          padding: '24px 28px',
          background: 'var(--paper)',
        }}
      >
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

        <div className="flex items-center justify-between gap-4 mb-4">
          <div>
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontStyle: 'italic',
                fontSize: 22,
                color: 'var(--ink)',
              }}
            >
              {t('podcast.today_title')}
            </div>
            <div
              className="uppercase mt-1"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                letterSpacing: '0.18em',
                color: 'var(--ink-mid)',
              }}
            >
              NotebookLM Audio
            </div>
          </div>

          <button
            type="button"
            onClick={togglePlayPause}
            disabled={isLoading || !hasAudio}
            aria-label={isPlaying ? t('podcast.pause') : t('podcast.play')}
            className="podcast-play-btn"
            style={{
              width: 56,
              height: 56,
              borderRadius: '50%',
              border: '1.5px solid var(--ink)',
              background: 'var(--paper)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: hasAudio ? 'pointer' : 'not-allowed',
              opacity: hasAudio ? 1 : 0.4,
              flexShrink: 0,
              transition: 'background 150ms',
            }}
          >
            {isLoading || isBuffering || (hasAudio && !isAudioReady) ? (
              <Loader2
                className="h-5 w-5 animate-spin"
                style={{ color: 'var(--ink)' }}
              />
            ) : isPlaying ? (
              <PauseIcon className="h-6 w-6" style={{ color: 'var(--ink)' }} />
            ) : (
              <PlayIcon
                className="h-6 w-6 ml-0.5"
                style={{ color: 'var(--ink)' }}
              />
            )}
          </button>
        </div>

        {/* Waveform */}
        {hasAudio ? (
          <div
            ref={waveformRef}
            className="flex items-center gap-[2px] cursor-pointer"
            onClick={handleWaveformClick}
            role="progressbar"
            aria-label={t('podcast.audio_progress')}
            aria-valuemin={0}
            aria-valuemax={duration || 100}
            aria-valuenow={currentTime}
            aria-valuetext={formatTime(currentTime)}
            style={{ height: 56 }}
          >
            {barHeights.map((height, i) => {
              const barProgress = (i + 0.5) / BAR_COUNT;
              const isActive = barProgress <= progress;
              return (
                <div
                  key={i}
                  style={{
                    flex: 1,
                    minWidth: 2,
                    height: `${height * 100}%`,
                    background: isActive ? 'var(--ink)' : 'var(--rule)',
                    transition: 'background 100ms',
                  }}
                />
              );
            })}
          </div>
        ) : (
          <div
            className="flex items-center justify-center h-14"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--ink-light)',
              letterSpacing: '0.1em',
            }}
          >
            {isLoading ? t('podcast.loading_short') : t('podcast.no_bulletin')}
          </div>
        )}

        <div
          className="flex justify-between mt-2 tabular-nums"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--ink-mid)',
          }}
        >
          <span>{hasAudio ? formatTime(currentTime) : '—'}</span>
          <span>{hasAudio && duration > 0 ? formatTime(duration) : '—'}</span>
        </div>
      </div>
    </section>
  );
}
