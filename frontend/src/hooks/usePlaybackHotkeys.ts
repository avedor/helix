import { useEffect, useRef } from 'react'

export type PlaybackHotkeyHandlers = {
  togglePlay: () => void
  next: () => void
  previous: () => void
  seekBy: (seconds: number) => void
  adjustVolume: (delta: number) => void
}

const SEEK_STEP_SECONDS = 5
const VOLUME_STEP = 0.05

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  if (tag === 'BUTTON' || tag === 'A') return true
  return Boolean(target.closest('button, a, [role="button"]'))
}

/**
 * Global keyboard shortcuts for the player transport. Mirrors the on-screen
 * controls so playback can be driven without a mouse.
 *
 * Space / K  play-pause
 * ArrowRight / ArrowLeft  seek by 5s
 * Shift+ArrowRight / N    next track
 * Shift+ArrowLeft / P     previous track
 * ArrowUp / ArrowDown     volume up / down
 */
export function usePlaybackHotkeys(handlers: PlaybackHotkeyHandlers) {
  // Callers pass a fresh object each render; keep the handlers in a ref so the
  // listener can register once and still call the latest closures.
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (isTypingTarget(event.target)) return
      // Open modals own the keyboard while they are on screen.
      if (document.querySelector('[aria-modal="true"]')) return

      const handlers = handlersRef.current

      switch (event.key) {
        case ' ':
          // Let a focused button/link handle Space natively instead of double firing.
          if (isInteractiveTarget(event.target)) return
          if (event.repeat) return
          event.preventDefault()
          handlers.togglePlay()
          break
        case 'k':
        case 'K':
          event.preventDefault()
          handlers.togglePlay()
          break
        case 'ArrowRight':
          event.preventDefault()
          if (event.shiftKey) handlers.next()
          else handlers.seekBy(SEEK_STEP_SECONDS)
          break
        case 'ArrowLeft':
          event.preventDefault()
          if (event.shiftKey) handlers.previous()
          else handlers.seekBy(-SEEK_STEP_SECONDS)
          break
        case 'n':
        case 'N':
          handlers.next()
          break
        case 'p':
        case 'P':
          handlers.previous()
          break
        case 'ArrowUp':
          event.preventDefault()
          handlers.adjustVolume(VOLUME_STEP)
          break
        case 'ArrowDown':
          event.preventDefault()
          handlers.adjustVolume(-VOLUME_STEP)
          break
        default:
          break
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])
}
