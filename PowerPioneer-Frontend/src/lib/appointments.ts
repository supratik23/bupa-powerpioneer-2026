import type { Appointment, Shift } from "../api/types";
import { isoDate } from "./format";

/** Local yyyy-mm-dd a shift belongs to (its start day; night shifts keep their start date). */
export const shiftDay = (shift: Shift) => isoDate(new Date(shift.shift_start));

export const isCompleted = (a: Appointment) => a.status === "COMPLETED";
