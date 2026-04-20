export function connectSse(path: string): EventSource {
  return new EventSource(`/api${path}`, {
    withCredentials: true
  });
}
