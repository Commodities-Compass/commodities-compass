import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/utils';
import { PlayIcon, PauseIcon, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { usePositionStatus, useAudio } from '@/hooks/useDashboard';
import { useRef, useEffect, useState, useCallback } from 'react';

interface PositionStatusProps {
  targetDate?: string;
  audioDate?: string;
  className?: string;
}

export default function PositionStatus({
  targetDate,
  audioDate,
  className,
}: PositionStatusProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const audioRef = useRef<HTMLAudioElement | null>(null);

  const { data, isLoading, error } = usePositionStatus(targetDate);
  const {
    data: audioData,
    isLoading: audioLoading,
    error: audioError,
  } = useAudio(audioDate);

  const setupAudioSource = useCallback(() => {
    if (audioRef.current && audioData?.url) {
      const apiBaseUrl = import.meta.env.API_BASE_URL || '';
      const absoluteUrl = audioData.url.startsWith('/')
        ? `${apiBaseUrl}${audioData.url}`
        : audioData.url;
      audioRef.current.src = absoluteUrl;
      audioRef.current.load();
      setIsPlaying(false);
      setCurrentTime(0);
      if (audioRef.current.duration) {
        setDuration(audioRef.current.duration);
      }
    }
  }, [audioData?.url]);

  useEffect(() => {
    setupAudioSource();
  }, [setupAudioSource]);

  const togglePlayPause = useCallback(() => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
      } else {
        audioRef.current.play().catch((err: unknown) => {
          const message = err instanceof Error ? err.message : 'Unknown error';
          console.error('Audio play failed:', message);
        });
      }
      setIsPlaying(!isPlaying);
    }
  }, [isPlaying]);

  const handleTimeUpdate = useCallback(() => {
    if (audioRef.current) {
      setCurrentTime(audioRef.current.currentTime);
    }
  }, []);

  const handleLoadedMetadata = useCallback(() => {
    if (audioRef.current) {
      setDuration(audioRef.current.duration);
    }
  }, []);

  const handleEnded = useCallback(() => {
    setIsPlaying(false);
  }, []);

  const handleProgressChange = (value: number[]) => {
    if (audioRef.current) {
      audioRef.current.currentTime = value[0];
      setCurrentTime(value[0]);
    }
  };

  const formatTime = (time: number) => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`;
  };

  if (isLoading) {
    return (
      <Card
        className={cn('flex items-center justify-center h-[180px]', className)}
      >
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card
        className={cn('flex items-center justify-center h-[180px]', className)}
      >
        <div className="text-center space-y-2">
          <p className="text-sm text-muted-foreground">
            Unable to load position status
          </p>
          {error && (
            <p className="text-xs text-red-500">
              Unable to fetch data. Please try again later.
            </p>
          )}
          <p className="text-xs text-gray-400">Target date: {targetDate}</p>
        </div>
      </Card>
    );
  }

  const { position, ytd_performance } = data;

  const getBadgeStyles = () => {
    switch (position) {
      case 'HEDGE':
        return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
      case 'MONITOR':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300';
      case 'OPEN':
        return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-300';
    }
  };

  return (
    <Card className={cn('flex flex-col md:flex-row h-[180px]', className)}>
      <div className="flex-1 border-b md:border-b-0 md:border-r border-border flex flex-col justify-between">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Position of the Day
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center py-6 flex-grow">
          <Badge
            className={cn('text-xl font-bold px-8 py-3', getBadgeStyles())}
          >
            {position}
          </Badge>
        </CardContent>
      </div>

      <div className="flex-1 border-b md:border-b-0 md:border-r border-border flex flex-col justify-between">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-gray-500 dark:text-gray-400">
            {audioData?.title || 'Compass Bulletin'}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center py-4 flex-grow">
          <div className="w-full space-y-4">
            <audio
              ref={audioRef}
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={handleLoadedMetadata}
              onEnded={handleEnded}
            />

            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                size="icon"
                className="h-10 w-10 flex-shrink-0"
                onClick={togglePlayPause}
                disabled={audioLoading || !audioData?.url}
                aria-label={isPlaying ? 'Pause audio' : 'Play audio'}
              >
                {audioLoading ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : isPlaying ? (
                  <PauseIcon className="h-5 w-5" />
                ) : (
                  <PlayIcon className="h-5 w-5" />
                )}
              </Button>

              <div className="flex-1">
                <Slider
                  value={[currentTime]}
                  max={duration || 100}
                  step={0.1}
                  onValueChange={handleProgressChange}
                  className="w-full"
                />
              </div>

              <span className="text-sm text-gray-500 dark:text-gray-400 min-w-[80px] text-right flex-shrink-0">
                {audioError ? (
                  <span className="text-red-500">Error</span>
                ) : audioLoading ? (
                  'Loading...'
                ) : (
                  `${formatTime(currentTime)} / ${formatTime(duration)}`
                )}
              </span>
            </div>
            {audioError && (
              <p className="text-xs text-red-500 mt-2">
                Unable to load audio file.
              </p>
            )}
          </div>
        </CardContent>
      </div>

      <div className="flex-1 flex flex-col justify-between">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-gray-500 dark:text-gray-400">
            YTD Performance
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center py-6 flex-grow">
          <div className="text-3xl font-bold">
            {ytd_performance.toFixed(2)}%
          </div>
        </CardContent>
      </div>
    </Card>
  );
}
