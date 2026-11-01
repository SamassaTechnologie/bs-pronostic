"use client";
import { useCallback, useEffect, useState } from "react";

/** Coupon de la section Jouer : conservé sur cet appareil (navigateur), sans valeur côté serveur. */
export type CouponSel = { match_id: number; market_key: string; label: string; match: string; odds: number };

const KEY = "sam-coupon-v1";
const EVENT = "sam-coupon-change";

function read(): CouponSel[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as CouponSel[]) : [];
  } catch {
    return [];
  }
}

function write(list: CouponSel[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {}
  window.dispatchEvent(new Event(EVENT));
}

export function useCoupon() {
  const [items, setItems] = useState<CouponSel[]>([]);
  useEffect(() => {
    const sync = () => setItems(read());
    sync();
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const has = useCallback((mid: number, key: string) => items.some((s) => s.match_id === mid && s.market_key === key), [items]);
  const toggle = useCallback((sel: CouponSel) => {
    const cur = read();
    const exists = cur.some((s) => s.match_id === sel.match_id && s.market_key === sel.market_key);
    // Une seule sélection par match : choisir une autre issue du même match remplace la précédente.
    const next = exists
      ? cur.filter((s) => !(s.match_id === sel.match_id && s.market_key === sel.market_key))
      : [...cur.filter((s) => s.match_id !== sel.match_id), sel].slice(-10);
    write(next);
  }, []);
  const remove = useCallback((mid: number, key: string) => write(read().filter((s) => !(s.match_id === mid && s.market_key === key))), []);
  const clear = useCallback(() => write([]), []);
  const total = items.reduce((t, s) => t * s.odds, 1);
  return { items, has, toggle, remove, clear, total };
}
