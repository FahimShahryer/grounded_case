"use server";

import { revalidatePath } from "next/cache";
import { runMiner } from "@/lib/api";

export async function runMinerAction() {
  const res = await runMiner();
  revalidatePath("/learning");
  revalidatePath("/");
  return res;
}
