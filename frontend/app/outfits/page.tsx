"use client";

import { useState, useRef, useEffect } from "react";

/* ── Types ─────────────────────────────────────────────────────────── */

interface OutfitItem {
  id: number;
  category: string;
  subcategory: string;
  color: string;
  description: string;
  image_url: string;
}

interface Weather {
  temp_c: number;
  temp_f: number;
  humidity: number;
  condition: string;
  wind_speed_kmh: number;
}

interface OutfitResponse {
  top?: OutfitItem;
  bottom?: OutfitItem;
  dress?: OutfitItem;
  shoes?: OutfitItem;
  reasoning: string;
  prompt: string;
  weather: Weather;
  city: string;
  error?: string;
}

const SUGGESTIONS = [
  "Casual outfit for today",
  "Date night in NYC",
  "Brunch with friends",
  "Hiking in mild weather",
  "Office meeting look",
  "Travel day — comfy but cute",
];

/* ── Weather Badge ─────────────────────────────────────────────────── */

function WeatherBadge({ weather, city }: { weather: Weather; city: string }) {
  const conditionIcon: Record<string, string> = {
    clear: "sunny",
    "mainly clear": "sunny",
    sunny: "sunny",
    "partly cloudy": "partly_cloudy_day",
    cloudy: "cloud",
    overcast: "cloud",
    rain: "rainy",
    drizzle: "rainy",
    "light rain": "rainy",
    snow: "ac_unit",
    fog: "foggy",
    mist: "foggy",
  };

  const icon = conditionIcon[weather.condition.toLowerCase()] || "thermostat";

  return (
    <div className="inline-flex items-center gap-3 px-4 py-2.5 rounded-xl bg-cream-dark/60 border border-border text-sm">
      <span
        className="material-symbols-outlined text-taupe"
        style={{ fontSize: "20px" }}
      >
        {icon}
      </span>
      <span className="capitalize text-charcoal/70">{city}</span>
      <span className="text-charcoal font-medium">
        {Math.round(weather.temp_c)}°C
      </span>
      <span className="text-charcoal/40 capitalize">{weather.condition}</span>
    </div>
  );
}

/* ── Outfit Piece Card ─────────────────────────────────────────────── */

function PieceCard({ item, slot }: { item: OutfitItem; slot: string }) {
  const [loaded, setLoaded] = useState(false);

  return (
    <div
      className="animate-fade-in rounded-xl overflow-hidden bg-warm-white"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      {/* Image */}
      <div className="aspect-[3/4] bg-cream-dark rounded-t-xl overflow-hidden relative">
        <img
          src={item.image_url + "/card"}
          alt={item.subcategory}
          onLoad={() => setLoaded(true)}
          className={`w-full h-full object-cover transition-opacity duration-500 ${
            loaded ? "opacity-100" : "opacity-0"
          }`}
        />
        {/* Slot badge */}
        <span className="absolute top-3 left-3 px-3 py-1 text-[11px] tracking-widest uppercase rounded-full bg-warm-white/90 backdrop-blur-sm text-charcoal/70 border border-border">
          {slot}
        </span>
      </div>

      {/* Details */}
      <div className="px-4 pt-3 pb-4">
        <h3 className="text-sm font-medium capitalize">{item.subcategory}</h3>
        <p className="text-xs text-charcoal/45 mt-0.5 capitalize">
          {item.color}
        </p>
        {item.description && (
          <p className="text-xs text-charcoal/40 mt-2 line-clamp-2 leading-relaxed">
            {item.description}
          </p>
        )}
      </div>
    </div>
  );
}

/* ── Skeleton ──────────────────────────────────────────────────────── */

function OutfitSkeleton() {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-3 gap-5 max-w-3xl">
      {[0, 1, 2].map((i) => (
        <div key={i} className="rounded-xl overflow-hidden">
          <div className="skeleton aspect-[3/4]" />
          <div className="pt-3 px-4 pb-4 space-y-2">
            <div className="skeleton h-4 w-3/4 rounded" />
            <div className="skeleton h-3 w-1/2 rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── History Entry ─────────────────────────────────────────────────── */

interface HistoryEntry {
  prompt: string;
  result: OutfitResponse;
  timestamp: number;
}

/* ── Main Page ─────────────────────────────────────────────────────── */

export default function OutfitsPage() {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<OutfitResponse | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSubmit(text?: string) {
    const query = (text || prompt).trim();
    if (!query || loading) return;

    setLoading(true);
    setResult(null);

    try {
      const res = await fetch(
        `/api/wardrobe/outfit?prompt=${encodeURIComponent(query)}`,
        { method: "POST" }
      );
      const data: OutfitResponse = await res.json();
      setResult(data);

      if (!data.error) {
        setHistory((prev) => [
          { prompt: query, result: data, timestamp: Date.now() },
          ...prev.slice(0, 9),
        ]);
      }
    } catch (err) {
      console.error("Outfit request failed:", err);
      setResult({ error: "Could not reach the API." } as OutfitResponse);
    } finally {
      setLoading(false);
    }
  }

  const pieces: { slot: string; item: OutfitItem }[] = [];
  if (result && !result.error) {
    if (result.dress) pieces.push({ slot: "Dress", item: result.dress });
    if (result.top) pieces.push({ slot: "Top", item: result.top });
    if (result.bottom) pieces.push({ slot: "Bottom", item: result.bottom });
    if (result.shoes) pieces.push({ slot: "Shoes", item: result.shoes });
  }

  return (
    <div className="max-w-7xl mx-auto px-6">
      {/* Google Material Symbols for weather icons */}
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap"
      />

      {/* Hero */}
      <section className="pt-12 pb-6">
        <h2 className="font-serif text-4xl md:text-5xl tracking-tight">
          Outfit Studio
        </h2>
        <p className="text-charcoal/50 mt-2 text-lg">
          Describe the vibe — I&apos;ll pull from your closet
        </p>
      </section>

      {/* Prompt Input */}
      <div className="max-w-2xl pb-6">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
          className="flex gap-3"
        >
          <input
            ref={inputRef}
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. party outfit in NYC tonight..."
            className="flex-1 px-5 py-3.5 rounded-xl bg-warm-white border border-border text-sm
                       placeholder:text-charcoal/30 focus:outline-none focus:border-taupe
                       transition-colors"
          />
          <button
            type="submit"
            disabled={loading || !prompt.trim()}
            className="px-6 py-3.5 rounded-xl bg-charcoal text-warm-white text-sm font-medium
                       hover:bg-charcoal/90 disabled:opacity-40 disabled:cursor-not-allowed
                       transition-all"
          >
            {loading ? "Styling..." : "Style me"}
          </button>
        </form>

        {/* Quick suggestions */}
        {!result && !loading && (
          <div className="flex flex-wrap gap-2 mt-4">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => {
                  setPrompt(s);
                  handleSubmit(s);
                }}
                className="px-4 py-2 rounded-full text-xs border border-border text-charcoal/50
                           hover:border-taupe hover:text-charcoal bg-transparent transition-all"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <section className="pb-12">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-2 h-2 rounded-full bg-blush animate-pulse" />
            <p className="text-sm text-charcoal/50">
              Searching your closet...
            </p>
          </div>
          <OutfitSkeleton />
        </section>
      )}

      {/* Error */}
      {result?.error && (
        <section className="pb-12">
          <div className="max-w-md p-6 rounded-xl bg-warm-white border border-border">
            <p className="text-sm text-charcoal/60">{result.error}</p>
          </div>
        </section>
      )}

      {/* Result */}
      {result && !result.error && pieces.length > 0 && (
        <section className="pb-16 animate-fade-in">
          {/* Weather + Reasoning */}
          <div className="flex flex-col gap-3 mb-8">
            {result.weather && (
              <WeatherBadge weather={result.weather} city={result.city} />
            )}
            <p className="text-sm text-charcoal/60 leading-relaxed max-w-xl">
              {result.reasoning}
            </p>
          </div>

          {/* Outfit Pieces */}
          <div
            className={`grid gap-5 ${
              pieces.length <= 2
                ? "grid-cols-2 max-w-lg"
                : "grid-cols-2 lg:grid-cols-3 max-w-3xl"
            }`}
          >
            {pieces.map(({ slot, item }, i) => (
              <div
                key={item.id}
                style={{ animationDelay: `${i * 100}ms` }}
              >
                <PieceCard item={item} slot={slot} />
              </div>
            ))}
          </div>

          {/* Try again */}
          <button
            onClick={() => {
              setResult(null);
              setPrompt("");
              inputRef.current?.focus();
            }}
            className="mt-8 px-5 py-2.5 rounded-full text-sm border border-border text-charcoal/50
                       hover:border-taupe hover:text-charcoal transition-all"
          >
            Try another look
          </button>
        </section>
      )}

      {/* History */}
      {history.length > 0 && !loading && (
        <section className="border-t border-border pt-10 pb-16">
          <h3 className="font-serif text-xl mb-6 text-charcoal/70">
            Recent looks
          </h3>
          <div className="space-y-4">
            {history.map((entry, i) => {
              const entryPieces: OutfitItem[] = [];
              if (entry.result.dress) entryPieces.push(entry.result.dress);
              if (entry.result.top) entryPieces.push(entry.result.top);
              if (entry.result.bottom) entryPieces.push(entry.result.bottom);
              if (entry.result.shoes) entryPieces.push(entry.result.shoes);

              return (
                <button
                  key={entry.timestamp}
                  onClick={() => {
                    setPrompt(entry.prompt);
                    setResult(entry.result);
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  }}
                  className="w-full flex items-center gap-4 p-4 rounded-xl bg-warm-white border border-border
                             hover:border-taupe text-left transition-all group"
                  style={{ boxShadow: "var(--shadow-card)" }}
                >
                  {/* Thumbnails */}
                  <div className="flex -space-x-3">
                    {entryPieces.slice(0, 3).map((item) => (
                      <div
                        key={item.id}
                        className="w-10 h-10 rounded-full border-2 border-warm-white overflow-hidden bg-cream-dark"
                      >
                        <img
                          src={item.image_url + "/card"}
                          alt={item.subcategory}
                          className="w-full h-full object-cover"
                        />
                      </div>
                    ))}
                  </div>

                  {/* Text */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">
                      {entry.prompt}
                    </p>
                    <p className="text-xs text-charcoal/40 mt-0.5">
                      {entryPieces.length} pieces
                      {entry.result.city && entry.result.city !== "local" && (
                        <span> &middot; {entry.result.city}</span>
                      )}
                      {entry.result.weather && (
                        <span>
                          {" "}
                          &middot; {Math.round(entry.result.weather.temp_c)}°C{" "}
                          {entry.result.weather.condition}
                        </span>
                      )}
                    </p>
                  </div>

                  {/* Arrow */}
                  <span className="text-charcoal/20 group-hover:text-charcoal/50 transition-colors text-lg">
                    &rsaquo;
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
