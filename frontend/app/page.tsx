"use client";

import { useEffect, useState, useRef, useCallback } from "react";

/* ── Types ─────────────────────────────────────────────────────────── */

interface WardrobeItem {
  id: number;
  category: string;
  subcategory: string;
  color: string;
  pattern: string;
  season: string;
  comfort: string;
  style_tags: string | string[];
  suited_for: string;
  description: string;
  image_url: string | null;
}

interface ApiResponse {
  items: WardrobeItem[];
  summary: { total_items: number; by_category: Record<string, number> };
}

const CATEGORIES = ["all", "tops", "bottoms", "dresses", "shoes"] as const;

const CATEGORY_LABELS: Record<string, string> = {
  all: "All Pieces",
  tops: "Tops",
  bottoms: "Bottoms",
  dresses: "Dresses",
  shoes: "Shoes",
};

/* ── Skeleton Card ─────────────────────────────────────────────────── */

function SkeletonCard() {
  return (
    <div className="rounded-xl overflow-hidden">
      <div className="skeleton aspect-[3/4]" />
      <div className="pt-3 space-y-2">
        <div className="skeleton h-4 w-3/4 rounded" />
        <div className="skeleton h-3 w-1/2 rounded" />
      </div>
    </div>
  );
}

/* ── Lazy Image with Fade-In ───────────────────────────────────────── */

function LazyImage({ src, alt, eager = false }: { src: string; alt: string; eager?: boolean }) {
  const imgRef = useRef<HTMLDivElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [inView, setInView] = useState(eager);

  useEffect(() => {
    if (eager) return;
    const el = imgRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [eager]);

  return (
    <div ref={imgRef} className="aspect-[3/4] bg-cream-dark rounded-xl overflow-hidden">
      {inView && (
        <img
          src={src}
          alt={alt}
          onLoad={() => setLoaded(true)}
          className={`w-full h-full object-cover card-image transition-opacity duration-500 ${
            loaded ? "opacity-100" : "opacity-0"
          }`}
        />
      )}
    </div>
  );
}

/* ── Quick-View Modal ──────────────────────────────────────────────── */

function QuickView({
  item,
  onClose,
}: {
  item: WardrobeItem;
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const tags =
    typeof item.style_tags === "string"
      ? (() => { try { return JSON.parse(item.style_tags || "[]"); } catch { return []; } })()
      : item.style_tags || [];

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      onClick={onClose}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-charcoal/30 backdrop-blur-sm animate-fade-in" />

      {/* Modal */}
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative bg-warm-white rounded-2xl overflow-hidden max-w-3xl w-full grid grid-cols-1 md:grid-cols-2 animate-fade-in"
        style={{ boxShadow: "var(--shadow-modal)" }}
      >
        {/* Image */}
        <div className="aspect-[3/4] bg-cream-dark">
          {item.image_url && (
            <img
              src={item.image_url + "/card"}
              alt={item.subcategory}
              className="w-full h-full object-cover"
            />
          )}
        </div>

        {/* Details */}
        <div className="p-8 flex flex-col justify-center">
          <button
            onClick={onClose}
            className="absolute top-4 right-4 w-8 h-8 flex items-center justify-center rounded-full bg-cream hover:bg-cream-dark transition-colors text-charcoal/60 text-lg"
          >
            &times;
          </button>

          <p className="text-xs tracking-widest uppercase text-taupe mb-2">
            {item.category}
          </p>
          <h2 className="font-serif text-2xl mb-1 capitalize">
            {item.subcategory}
          </h2>
          <p className="text-charcoal/50 text-sm mb-6 capitalize">{item.color}</p>

          {item.description && (
            <p className="text-sm leading-relaxed text-charcoal/70 mb-6">
              {item.description}
            </p>
          )}

          <div className="space-y-3 text-sm">
            <div className="flex justify-between py-2 border-b border-border">
              <span className="text-charcoal/50">Season</span>
              <span className="capitalize">{item.season?.replace(/_/g, " ")}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-border">
              <span className="text-charcoal/50">Style</span>
              <span className="capitalize">{item.comfort?.replace(/_/g, " ")}</span>
            </div>
            {item.pattern && item.pattern !== "solid" && (
              <div className="flex justify-between py-2 border-b border-border">
                <span className="text-charcoal/50">Pattern</span>
                <span className="capitalize">{item.pattern}</span>
              </div>
            )}
            {item.suited_for && (
              <div className="flex justify-between py-2 border-b border-border">
                <span className="text-charcoal/50">Best for</span>
                <span className="capitalize">{item.suited_for}</span>
              </div>
            )}
          </div>

          {tags.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-6">
              {tags.map((tag: string) => (
                <span
                  key={tag}
                  className="px-3 py-1 text-xs rounded-full bg-cream text-charcoal/60 border border-border"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Item Card ─────────────────────────────────────────────────────── */

function ItemCard({
  item,
  index,
  onClick,
}: {
  item: WardrobeItem;
  index: number;
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className="group cursor-pointer card-hover rounded-xl transition-shadow duration-300 animate-fade-in"
      style={{
        animationDelay: `${index * 60}ms`,
        boxShadow: "var(--shadow-card)",
      }}
    >
      {/* Image */}
      <div className="rounded-t-xl overflow-hidden bg-warm-white">
        {item.image_url ? (
          <LazyImage
            src={item.image_url + "/card"}
            alt={item.subcategory}
            eager={index < 8}
          />
        ) : (
          <div className="aspect-[3/4] bg-cream-dark flex items-center justify-center text-taupe">
            No image
          </div>
        )}
      </div>

      {/* Meta */}
      <div className="px-3 pt-3 pb-4 bg-warm-white rounded-b-xl">
        <h3 className="text-sm font-medium capitalize truncate">
          {item.subcategory}
        </h3>
        <p className="text-xs text-charcoal/45 mt-0.5 capitalize">
          {item.color}
          {item.season && item.season !== "all_season" && (
            <span> &middot; {item.season.replace(/_/g, " ")}</span>
          )}
        </p>
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────── */

export default function BrowsePage() {
  const [items, setItems] = useState<WardrobeItem[]>([]);
  const [summary, setSummary] = useState<ApiResponse["summary"] | null>(null);
  const [activeCategory, setActiveCategory] = useState("all");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<WardrobeItem | null>(null);

  const fetchItems = useCallback(async (category: string) => {
    setLoading(true);
    try {
      const url =
        category === "all"
          ? "/api/wardrobe/items"
          : `/api/wardrobe/items?category=${category}`;
      const res = await fetch(url);
      const data: ApiResponse = await res.json();
      setItems(data.items);
      setSummary(data.summary);
    } catch (err) {
      console.error("Failed to fetch wardrobe:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchItems(activeCategory);
  }, [activeCategory, fetchItems]);

  return (
    <div className="max-w-7xl mx-auto px-6">
      {/* Hero */}
      <section className="pt-12 pb-8">
        <h2 className="font-serif text-4xl md:text-5xl tracking-tight">
          My Wardrobe
        </h2>
        <p className="text-charcoal/50 mt-2 text-lg">
          {summary?.total_items ?? "..."} pieces, curated with intention
        </p>
      </section>

      {/* Filter Pills */}
      <div className="flex gap-2 pb-8 overflow-x-auto">
        {CATEGORIES.map((cat) => {
          const isActive = activeCategory === cat;
          const count =
            cat === "all"
              ? summary?.total_items
              : summary?.by_category[cat];

          return (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`pill-active px-5 py-2 rounded-full text-sm whitespace-nowrap border transition-all ${
                isActive
                  ? "bg-charcoal text-warm-white border-charcoal"
                  : "bg-transparent text-charcoal/60 border-border hover:border-taupe hover:text-charcoal"
              }`}
            >
              {CATEGORY_LABELS[cat]}
              {count !== undefined && (
                <span className={`ml-1.5 ${isActive ? "text-warm-white/60" : "text-charcoal/30"}`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Grid */}
      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
          {Array.from({ length: 8 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-20 text-charcoal/40">
          <p className="font-serif text-xl">Nothing here yet</p>
          <p className="text-sm mt-2">Add items through the API to get started</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
          {items.map((item, i) => (
            <ItemCard
              key={item.id}
              item={item}
              index={i}
              onClick={() => setSelected(item)}
            />
          ))}
        </div>
      )}

      {/* Quick-View Modal */}
      {selected && (
        <QuickView item={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
