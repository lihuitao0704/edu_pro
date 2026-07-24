const eventName = 'wealth:profile-updated'

export function publishProfileUpdated(customerId: number) {
  window.dispatchEvent(new CustomEvent<number>(eventName, { detail: customerId }))
}

export function onProfileUpdated(listener: (customerId: number) => void) {
  const handler = (event: Event) => listener((event as CustomEvent<number>).detail)
  window.addEventListener(eventName, handler)
  return () => window.removeEventListener(eventName, handler)
}
