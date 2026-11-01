import { userTz } from "@/lib/api";
import { JouerCoupon } from "@/components/jouer/JouerCoupon";

export const dynamic = "force-dynamic";
export const metadata = { title: "Coupon" };

export default async function CouponPage() {
  return <JouerCoupon tz={await userTz()} />;
}
