/** Splits a heading line into words that rise 24px and fade in, 80ms apart. */
export default function Words({ text, start = 0 }: { text: string; start?: number }) {
  return (
    <>
      {text.split(" ").map((word, i) => (
        <span key={i} className="ss-word" style={{ animationDelay: `${(start + i) * 80}ms` }}>
          {word}
          {i < text.split(" ").length - 1 ? " " : ""}
        </span>
      ))}
    </>
  );
}
