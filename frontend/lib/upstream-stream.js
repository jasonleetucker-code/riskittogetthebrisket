// Time only an active upstream read. Downstream backpressure must not abort a
// healthy response; fetch exposes decoded bytes, so callers drop encoding/length.
export function streamWithUpstreamIdleAbort(res, ctl, timeoutMs = 4000) {
  const reader = res.body.getReader();
  return new ReadableStream({
    async pull(controller) {
      let timer;
      try {
        const idle = new Promise((_, reject) => {
          timer = setTimeout(() => {
            ctl.abort();
            reject(new Error("backend idle timeout"));
          }, timeoutMs);
        });
        const { done, value } = await Promise.race([reader.read(), idle]);
        clearTimeout(timer);
        if (done) controller.close();
        else controller.enqueue(value);
      } catch (error) {
        clearTimeout(timer);
        ctl.abort();
        controller.error(error);
      }
    },
    cancel(reason) {
      ctl.abort();
      return reader.cancel(reason);
    },
  });
}
