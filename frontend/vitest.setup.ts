import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest globals are off (tests import describe/it/expect explicitly), so React
// Testing Library's automatic cleanup does not register itself. Without this, one
// test's DOM leaks into the next and queries start matching the wrong render.
afterEach(cleanup);
