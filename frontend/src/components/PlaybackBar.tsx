import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { AudioIntent, PlaybackDevice, PlayerState, UserSettings, UserSettingsPayload } from '../api/types'
import type { AudioRunMode } from '../hooks/usePlayer'
import { Artwork } from './Artwork'
import { ArtistLink } from './ArtistLink'
import { AlbumLink } from './AlbumLink'
import { AudioPlayer } from './AudioPlayer'
import { deviceId } from '../device'

type PlaybarStyle = 'helix' | 'ytmusic' | 'spotify' | 'pandora'
type SkipDirection = 'previous' | 'next'

type UserSettingsWithPlaybar = UserSettings & { playback_bar_style?: PlaybarStyle }

type Props = {
  player: PlayerState | null
  audioIntent: AudioIntent
  run: (action: () => Promise<PlayerState>, audioMode?: AudioRunMode) => Promise<PlayerState>
  setPlayer: (player: PlayerState) => void
  setError?: (message: string) => void
  onTakeover: () => Promise<PlayerState>
  transportBusy?: boolean
}

function IconThumbDown() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h9.2c1.1 0 2 .72 2.3 1.78l1.2 4.3c.12.42.18.85.18 1.28V12c0 1.1-.9 2-2 2h-4.6l.74 3.5c.13.62-.06 1.27-.51 1.72L12.4 20.33 6.9 14.8V5.1C6.9 3.94 5.96 3 4.8 3H4v11h2.9" /></svg>
  )
}

function IconThumbUp() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><g transform="translate(24 0) scale(-1 1)"><path d="M17 21H7.8c-1.1 0-2-.72-2.3-1.78l-1.2-4.3a4.7 4.7 0 0 1-.18-1.28V12c0-1.1.9-2 2-2h4.6l-.74-3.5c-.13-.62.06-1.27.51-1.72L11.6 3.67l5.5 5.53v9.7c0 1.16.94 2.1 2.1 2.1h.8V10h-2.9" /></g></svg>
  )
}

function IconRepeat() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 2l4 4-4 4" /><path d="M3 11V9a3 3 0 0 1 3-3h15" /><path d="M7 22l-4-4 4-4" /><path d="M21 13v2a3 3 0 0 1-3 3H3" /></svg>
  )
}

function IconPrevious() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5v14" /><path d="M19 6.5 9 12l10 5.5V6.5Z" /></svg>
  )
}

function IconNext() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 5v14" /><path d="M5 6.5 15 12 5 17.5V6.5Z" /></svg>
  )
}

function IconPlay() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5-11-6.5Z" /></svg>
  )
}

function IconPause() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14" /><path d="M16 5v14" /></svg>
  )
}

function IconLyrics() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5h10" /><path d="M5 9h10" /><path d="M5 13h7" /><path d="M17 12v6.5a2.5 2.5 0 1 1-2-2.45V8l4-1" /></svg>
  )
}

function IconDevices() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="12" height="8.5" rx="1.3" /><path d="M6.5 20.5h6" /><path d="M9.5 16.5v4" /><rect x="16.8" y="10.5" width="4.2" height="7.5" rx="1.1" /></svg>
  )
}

function isPlaybarStyle(value: unknown): value is PlaybarStyle {
  return value === 'helix' || value === 'ytmusic' || value === 'spotify' || value === 'pandora'
}

export function PlaybackBar({ player, audioIntent, run, setPlayer, setError, onTakeover, transportBusy = false }: Props) {
  const navigate = useNavigate()
  const barRef = useRef<HTMLElement | null>(null)
  const [localPlaying, setLocalPlaying] = useState(false)
  const [liked, setLiked] = useState(false)
  const [disliked, setDisliked] = useState(false)
  const [ratingBusy, setRatingBusy] = useState(false)
  const [repeatTrack, setRepeatTrack] = useState(() => window.localStorage.getItem('helix.repeatTrack') === '1')
  const [playbarStyle, setPlaybarStyle] = useState<PlaybarStyle>('helix')
  const [skipDirection, setSkipDirection] = useState<SkipDirection | null>(null)
  const skipFeedbackTimerRef = useRef<number | null>(null)
  const [syncedDeviceName, setSyncedDeviceName] = useState('')
  const now = player?.now_playing
  const hasTrack = Boolean(now)
  const shouldKeepPlaying = Boolean(player?.is_playing || localPlaying)
  const trackIdentity = `${now?.subsonic_song_id ?? ''}|${now?.yt_video_id ?? ''}|${now?.id ?? ''}`
  const otherDeviceActive = Boolean(now && player?.active_device_id && player.active_device_id !== deviceId())
  const syncedDeviceId = otherDeviceActive ? player?.active_device_id ?? '' : ''

  useEffect(() => {
    if (!syncedDeviceId) {
      setSyncedDeviceName('')
      return
    }
    let cancelled = false
    void api.playerDevices().then((payload) => {
      if (cancelled) return
      const device = payload.devices.find((candidate) => candidate.id === syncedDeviceId)
      setSyncedDeviceName(device?.name ?? '')
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [syncedDeviceId])

  const myDeviceId = deviceId()
  const [devices, setDevices] = useState<PlaybackDevice[]>([])
  const [devicesOpen, setDevicesOpen] = useState(false)
  const [devicesLoading, setDevicesLoading] = useState(false)

  const refreshDevices = useCallback(() => {
    setDevicesLoading(true)
    return api.playerDevices()
      .then((payload) => { setDevices(payload.devices) })
      .catch(() => undefined)
      .finally(() => { setDevicesLoading(false) })
  }, [])

  // Keep the picker fresh while it is open, and whenever the owner changes so
  // "Playing" tracks the actual active device.
  useEffect(() => {
    if (!devicesOpen) return
    void refreshDevices()
  }, [devicesOpen, refreshDevices, player?.active_device_id])

  useEffect(() => {
    if (!devicesOpen) return
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('.device-picker')) return
      setDevicesOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [devicesOpen])

  useEffect(() => {
    let cancelled = false

    void api.userSettings().then((payload) => {
      const style = (payload.settings as UserSettingsWithPlaybar).playback_bar_style
      if (!cancelled && isPlaybarStyle(style)) setPlaybarStyle(style)
    }).catch(() => undefined)

    const listener = (event: Event) => {
      const payload = (event as CustomEvent<UserSettingsPayload>).detail
      const next = (payload?.settings as UserSettingsWithPlaybar | undefined)?.playback_bar_style
      if (isPlaybarStyle(next)) setPlaybarStyle(next)
    }
    window.addEventListener('helix-user-settings-updated', listener)

    return () => {
      cancelled = true
      window.removeEventListener('helix-user-settings-updated', listener)
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    async function loadRatingState() {
      if (!now) {
        setLiked(false)
        setDisliked(false)
        return
      }

      try {
        const [likeState, dislikeState] = await Promise.all([
          api.isLiked(now),
          api.isDisliked(now),
        ])
        if (cancelled) return
        setLiked(Boolean(likeState.liked))
        setDisliked(Boolean(dislikeState.disliked))
      } catch {
        if (cancelled) return
        setLiked(false)
        setDisliked(false)
      }
    }

    void loadRatingState()
    return () => {
      cancelled = true
    }
  }, [trackIdentity])

  useEffect(() => {
    window.localStorage.setItem('helix.repeatTrack', repeatTrack ? '1' : '0')
  }, [repeatTrack])

  useEffect(() => () => {
    if (skipFeedbackTimerRef.current !== null) window.clearTimeout(skipFeedbackTimerRef.current)
  }, [])

  useEffect(() => {
    if (playbarStyle !== 'ytmusic') return

    const syncProgress = () => {
      const bar = barRef.current
      if (!bar) return
      const input = bar.querySelector<HTMLInputElement>('.scrub-input')
      const value = Number(input?.value ?? 0)
      const max = Number(input?.max ?? 0)
      const percent = max > 0 && Number.isFinite(value)
        ? Math.max(0, Math.min(100, (value / max) * 100))
        : 0
      bar.style.setProperty('--helix-scrub-progress', `${percent}%`)
    }

    syncProgress()
    const timer = window.setInterval(syncProgress, 100)
    return () => {
      window.clearInterval(timer)
      barRef.current?.style.removeProperty('--helix-scrub-progress')
    }
  }, [playbarStyle, trackIdentity])

  function updateYtMusicSeek(clientX: number) {
    const bar = barRef.current
    if (!bar || playbarStyle !== 'ytmusic') return
    const input = bar.querySelector<HTMLInputElement>('.scrub-input')
    const max = Number(input?.max ?? 0)
    if (!input || !Number.isFinite(max) || max <= 0) return
    const rect = bar.getBoundingClientRect()
    if (rect.width <= 0) return
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    const nextValue = ratio * max
    input.value = String(nextValue)
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
    bar.style.setProperty('--helix-scrub-progress', `${ratio * 100}%`)
  }

  // Hand playback to another of this user's devices. The server moves ownership
  // and broadcasts; this device yields automatically when it sees the active
  // device change, and the target picks up the server position.
  async function movePlaybackTo(targetId: string, targetName: string) {
    if (!hasTrack || transportBusy) return
    try {
      const next = await api.transferPlayback(targetId)
      setPlayer(next)
      setDevicesOpen(false)
    } catch (err) {
      setError?.(err instanceof Error ? err.message : `Could not move playback to ${targetName}`)
    }
  }

  function runDirectionalSkip(direction: SkipDirection, action: () => Promise<PlayerState>) {
    setSkipDirection(null)
    window.requestAnimationFrame(() => {
      setSkipDirection(direction)
      if (skipFeedbackTimerRef.current !== null) window.clearTimeout(skipFeedbackTimerRef.current)
      skipFeedbackTimerRef.current = window.setTimeout(() => {
        setSkipDirection(null)
        skipFeedbackTimerRef.current = null
      }, 230)
    })
    void run(action, shouldKeepPlaying ? 'play' : 'pause')
  }

  async function toggleLike() {
    if (!now || ratingBusy) return
    setRatingBusy(true)
    try {
      const result = await api.toggleLike(now)
      setLiked(result.liked)
      if (result.liked) setDisliked(false)
    } catch (err) {
      setError?.(err instanceof Error ? err.message : 'Could not update liked state')
    } finally {
      setRatingBusy(false)
    }
  }

  async function toggleDislike() {
    if (!now || ratingBusy) return
    setRatingBusy(true)
    try {
      const result = await api.toggleDislike(now)
      setDisliked(result.disliked)
      if (result.disliked) setLiked(false)
    } catch (err) {
      setError?.(err instanceof Error ? err.message : 'Could not update disliked state')
    } finally {
      setRatingBusy(false)
    }
  }

  return (
    <footer ref={barRef} className={`playback-bar playback-style-${playbarStyle}`} data-playbar-style={playbarStyle} data-skip-direction={skipDirection ?? undefined}>
      <div className="now-playing">
        <Artwork src={now?.art_url} alt={now?.title ?? 'No track'} />
        <div className="now-playing-info">
          <div className="eyebrow">Now Playing</div>
          <div className="title">{now?.title ?? 'Nothing selected'}</div>
          <div className="muted now-playing-meta">{now ? <><ArtistLink artist={now.artist} />{now.album ? <><span className="now-playing-meta-separator" aria-hidden="true">•</span><AlbumLink album={now.album} artist={now.artist} source={now.source} /></> : null}</> : 'Search, queue, or start a station'}</div>
        </div>
        <div className="rating-controls" aria-label="Track controls">
          <button className="icon-button rating-button rating-dislike" aria-label="Dislike current track" title="Dislike" onClick={toggleDislike} disabled={!hasTrack || ratingBusy} data-active={disliked}>
            <IconThumbDown />
          </button>
          <button className="icon-button rating-button rating-like" aria-label="Like current track" title="Like" onClick={toggleLike} disabled={!hasTrack || ratingBusy} data-active={liked}>
            <IconThumbUp />
          </button>
          <button className="icon-button lyrics-launch" type="button" aria-label="Open lyrics" title="Lyrics" onClick={() => navigate('/big-picture?view=lyrics')} disabled={!hasTrack}>
            <IconLyrics />
          </button>
          <div className="device-picker">
            <button
              className="icon-button device-button"
              type="button"
              aria-label="Playback devices"
              title="Playback devices"
              aria-haspopup="menu"
              aria-expanded={devicesOpen}
              data-active={devicesOpen}
              data-synced={otherDeviceActive}
              onClick={() => setDevicesOpen((open) => !open)}
            >
              <IconDevices />
            </button>
            {devicesOpen ? (
              <div className="device-menu" role="menu" aria-label="Playback devices">
                <div className="device-menu-header">Playback devices</div>
                {devicesLoading && devices.length === 0 ? (
                  <div className="device-menu-empty">Loading…</div>
                ) : devices.length === 0 ? (
                  <div className="device-menu-empty">No other devices seen recently</div>
                ) : (
                  devices.map((device) => {
                    const mine = device.id === myDeviceId
                    const label = device.name || device.kind || 'Device'
                    if (!mine && !device.is_active) {
                      return (
                        <button
                          key={device.id}
                          type="button"
                          className="device-menu-item device-menu-item-action"
                          disabled={!hasTrack || transportBusy}
                          title={`Move playback to ${label}`}
                          onClick={() => void movePlaybackTo(device.id, label)}
                        >
                          <span className="device-menu-name">{label}</span>
                          <span className="device-menu-tags">
                            <span className="device-menu-tag device-menu-tag-action">Move here</span>
                          </span>
                        </button>
                      )
                    }
                    return (
                      <div key={device.id} className="device-menu-item" data-active={device.is_active} data-mine={mine}>
                        <span className="device-menu-name">{label}</span>
                        <span className="device-menu-tags">
                          {mine ? <span className="device-menu-tag">This device</span> : null}
                          {device.is_active ? <span className="device-menu-tag device-menu-tag-live">Playing</span> : null}
                        </span>
                      </div>
                    )
                  })
                )}
                {otherDeviceActive ? (
                  <button
                    type="button"
                    className="device-menu-action"
                    disabled={!hasTrack || transportBusy}
                    onClick={() => {
                      void onTakeover().then(() => refreshDevices()).catch(() => undefined)
                      setDevicesOpen(false)
                    }}
                  >
                    {syncedDeviceName ? `Play here instead of ${syncedDeviceName}` : 'Play here on this device'}
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <div className="transport-stack">
        <div className="transport">
          <button className="icon-button transport-side transport-previous" aria-label="Previous track" title="Previous" onClick={() => runDirectionalSkip('previous', api.previous)} disabled={!player}>
            <IconPrevious />
          </button>
          {localPlaying ? (
            <button className="primary transport-main" aria-label="Pause" title="Pause" onClick={() => run(api.pause, 'pause')} disabled={!hasTrack || transportBusy}>
              <IconPause />
            </button>
          ) : otherDeviceActive ? (
            <button className="primary transport-main" aria-label="Take over playback" title={syncedDeviceName ? `Play here instead of ${syncedDeviceName}` : 'Play here on this device'} onClick={() => void onTakeover()} disabled={!hasTrack || transportBusy}>
              <IconPlay />
            </button>
          ) : (
            <button className="primary transport-main" aria-label="Play" title="Play" onClick={() => run(api.resume, 'play')} disabled={!hasTrack || transportBusy}>
              <IconPlay />
            </button>
          )}
          <button className="icon-button transport-side transport-next" aria-label="Next track" title="Next" onClick={() => runDirectionalSkip('next', api.next)} disabled={!player}>
            <IconNext />
          </button>
          <button
            className="icon-button transport-extra transport-repeat"
            type="button"
            title={repeatTrack ? 'Repeat track on' : 'Repeat track off'}
            aria-label={repeatTrack ? 'Disable track repeat' : 'Enable track repeat'}
            aria-pressed={repeatTrack}
            data-active={repeatTrack}
            onClick={() => setRepeatTrack((enabled) => !enabled)}
            disabled={!hasTrack}
          >
            <IconRepeat />
          </button>
        </div>
      </div>

      <AudioPlayer
        player={player}
        audioIntent={audioIntent}
        onStateChange={setPlayer}
        repeatTrack={repeatTrack}
        onLocalPlayingChange={setLocalPlaying}
        onError={setError}
        syncedDeviceName={syncedDeviceName}
      />
      <div
        className="ytmusic-seek-hitbox"
        aria-hidden="true"
        onPointerDown={(event) => {
          if (playbarStyle !== 'ytmusic') return
          event.currentTarget.setPointerCapture(event.pointerId)
          updateYtMusicSeek(event.clientX)
        }}
        onPointerMove={(event) => {
          if (playbarStyle !== 'ytmusic') return
          if (event.currentTarget.hasPointerCapture(event.pointerId)) updateYtMusicSeek(event.clientX)
        }}
        onPointerUp={(event) => {
          if (playbarStyle !== 'ytmusic') return
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            updateYtMusicSeek(event.clientX)
            event.currentTarget.releasePointerCapture(event.pointerId)
          }
        }}
      />
      <div className="ytmusic-utility-repeat">
        <button
          className="icon-button transport-extra ytmusic-repeat-button"
          type="button"
          title={repeatTrack ? 'Repeat track on' : 'Repeat track off'}
          aria-label={repeatTrack ? 'Disable track repeat' : 'Enable track repeat'}
          aria-pressed={repeatTrack}
          data-active={repeatTrack}
          onPointerDown={(event) => event.stopPropagation()}
          onPointerUp={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation()
            setRepeatTrack((enabled) => !enabled)
          }}
          disabled={!hasTrack}
        >
          <IconRepeat />
        </button>
      </div>
    </footer>
  )
}
