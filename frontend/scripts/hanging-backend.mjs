// A backend that accepts TCP connections and never answers.
//
// This is the production failure mode of 2026-08-12, reduced to a
// harness.  The FastAPI process had exhausted its file descriptors
// (`OSError: [Errno 24] Too many open files` raised from
// `socket.accept()`), so the kernel completed every handshake into the
// listen backlog and the application never wrote a byte.  From the
// outside that is indistinguishable from a very slow server: nginx
// connected in 0.4 ms and then waited its full 300 s
// `proxy_read_timeout`.
//
// It is NOT the same as "the backend is down".  A refused connection
// fails in microseconds and every caller here already handles it.
// Silence is the case that hangs.
//
// Usage:
//   node scripts/hanging-backend.mjs [port]
//
// Then point the frontend at it and build:
//   BACKEND_API_URL=http://127.0.0.1:8123 npm run build
//
// The socket is held open deliberately — do not add a timeout here.

import net from "node:net";

const port = Number(process.argv[2] || 8123);
const held = [];

const server = net.createServer((socket) => {
  // Keep a reference so the socket is not garbage collected, and never
  // write to it.  `setKeepAlive` stops the OS from tearing the
  // connection down on its own, which would turn this into a
  // connection-reset test instead of a hang test.
  socket.setKeepAlive(true);
  held.push(socket);
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`hanging-backend listening on 127.0.0.1:${port}\n`);
});

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    for (const s of held) s.destroy();
    server.close(() => process.exit(0));
  });
}
