import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("mobile landing page and booking access", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your car.Your driver.Your time.");
  await expect(page.getByRole("img", { name: /professional chauffeur/i })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByLabel("Navigation", { exact: true }).click();
  await page.getByRole("navigation", { name: "Mobile navigation" }).getByText("Services").click();
  await expect(page.getByRole("heading", { name: "A driver for the time you need" })).toBeVisible();
  await page.goto("/customer/book");
  await expect(page).toHaveURL(/\/login\?next=/);
});

test("register, save a car, request and cancel a booking", async ({ page }) => {
  test.skip(process.env.PLAYWRIGHT_MUTATIONS !== "1", "Run only against an isolated database.");
  const email = randomUUID() + "@example.com";
  await page.goto("/register?next=%2Fcustomer%2Fbook%3Fplan%3Dhalf-day");
  await page.getByLabel("Full name").fill("Browser Customer");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("short");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Use at least 12 characters.")).toBeVisible();
  await page.getByLabel("Password").fill("long-browser-only-test-password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Add a vehicle to continue")).toBeVisible();
  await page.getByText("Add a vehicle to continue").click();
  await page.getByLabel("Vehicle name").fill("Honda City");
  await page.getByRole("button", { name: "Add vehicle" }).click();
  await expect(page.getByText("Honda City")).toBeVisible();
  await page.goto("/customer/book?plan=half-day");
  await page.getByLabel("Pickup address in Bengaluru").fill("Bengaluru test pickup");
  await page.getByRole("button", { name: "Get fare estimate" }).click();
  await expect(page.getByText("Estimated total")).toBeVisible();
  await page.getByRole("button", { name: "Submit booking request" }).click();
  await expect(page.getByRole("heading", { name: "Booking details" })).toBeVisible();
  await expect(page.getByText("searching", { exact: true }).filter({visible:true})).toBeVisible();
  page.once("dialog", dialog=>void dialog.accept());
  await page.getByRole("button", { name: "Cancel booking" }).click();
  await expect(page.getByText("cancelled", { exact: true }).filter({visible:true})).toBeVisible();
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/customer\/dashboard$/);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("mobile driver uses onboarding, Skill Passport, documents and live trip panels", async ({ page }) => {
  test.skip(process.env.PLAYWRIGHT_MUTATIONS !== "1", "Run only against an isolated database.");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/register?role=driver");
  await page.getByLabel("Full name").fill("Browser Driver");
  await page.getByLabel("Email").fill(randomUUID()+"@example.com");
  await page.getByLabel("Password").fill("long-browser-only-test-password");
  await page.getByRole("button",{name:"Create account"}).click();
  const navigation = page.getByLabel("Workspace section");
  await navigation.selectOption("onboarding");
  await page.getByLabel("Years of experience").fill("8");
  await page.getByLabel("Languages").fill("Kannada, English");
  await page.getByLabel("Emergency contact number").fill("+919999999998");
  await page.getByRole("checkbox").check();
  await page.getByRole("button",{name:"Save experience"}).click();
  await expect(page.getByRole("status").filter({hasText:"Saved."})).toBeVisible();
  await navigation.selectOption("skill-passport");
  await expect(page.getByLabel("Years of experience")).toHaveValue("8");
  await navigation.selectOption("documents");
  await expect(page.getByText("No licences submitted.")).toBeVisible();
  await navigation.selectOption("active-trip");
  await expect(page.getByText("No active assignment.")).toBeVisible();
  expect(await page.evaluate(()=>window.document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("admin can open every operations panel and search customer records", async ({ page }) => {
  test.skip(!process.env.PLAYWRIGHT_ADMIN_EMAIL || !process.env.PLAYWRIGHT_ADMIN_PASSWORD, "Requires an isolated admin account.");
  await page.goto("/login");
  await page.getByLabel("Email").fill(process.env.PLAYWRIGHT_ADMIN_EMAIL!);
  await page.getByLabel("Password").fill(process.env.PLAYWRIGHT_ADMIN_PASSWORD!);
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
  await expect(page).toHaveURL(/\/admin$/);
  const tabs = ["Customers","Drivers","Driver verification","Bookings","Live operations","Pricing","Commissions","Payments","Refunds","Payouts","Reports","Safety incidents","Reviews","Support","Notifications","Staff","Audit logs","Settings"];
  const navigation = page.getByRole("navigation",{name:"Workspace",exact:true});
  for (const tab of tabs) {
    await navigation.getByRole("link",{name:tab,exact:true}).click();
    await expect(page.getByRole("heading",{name:tab,level:1,exact:true})).toBeVisible();
    await expect(page.getByText("Loading…",{exact:true})).toHaveCount(0);
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  }
  await navigation.getByRole("link",{name:"Customers",exact:true}).click();
  await page.getByLabel("Search",{exact:true}).fill("absent-test-name");
  await page.getByRole("button",{name:"Search",exact:true}).click();
  await expect(page.getByText("No records found.")).toBeVisible();
  const received = page.waitForEvent("download");
  await page.getByRole("link",{name:"Export CSV"}).click();
  expect((await received).suggestedFilename()).toBe("customers.csv");
});

test("demo checkout gates trip start and issues no real receipt",async({browser})=>{
  test.skip(process.env.PLAYWRIGHT_DEMO!=="1" || !process.env.PLAYWRIGHT_ADMIN_EMAIL, "Requires demo mode and a disposable admin.");
  const baseURL=process.env.PLAYWRIGHT_BASE_URL??"http://localhost:3000";
  const customer=await browser.newContext({baseURL,viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  const driver=await browser.newContext({baseURL});
  const admin=await browser.newContext({baseURL});
  try {
    const url="/api/v1";
    const password="long-browser-only-test-password";
    const customerRegistration=await customer.request.post(url+"/auth/register",{data:{name:"Demo Browser Customer",email:randomUUID()+"@example.com",password,role:"customer"}});
    expect(customerRegistration.status()).toBe(201);
    const driverRegistration=await driver.request.post(url+"/auth/register",{data:{name:"Demo Browser Driver",email:randomUUID()+"@example.com",password,role:"driver"}});
    expect(driverRegistration.status()).toBe(201);
    expect((await admin.request.post(url+"/auth/login",{data:{email:process.env.PLAYWRIGHT_ADMIN_EMAIL,password:process.env.PLAYWRIGHT_ADMIN_PASSWORD}})).status()).toBe(200);
    const expiry=new Date(Date.now()+365*86400000).toISOString().slice(0,10);
    const document=await driver.request.post(url+"/drivers/documents",{multipart:{licence_number:"BROWSERTEST01",expiry,document:{name:"test.pdf",mimeType:"application/pdf",buffer:Buffer.from("%PDF-1.4 isolated browser fixture")}}});
    expect(document.status()).toBe(201);
    expect((await admin.request.post(url+"/admin/verifications/"+(await document.json()).id,{data:{decision:"APPROVED"}})).status()).toBe(200);
    expect((await driver.request.put(url+"/availability",{data:{area:"Bengaluru",transmission:"both",online:true}})).status()).toBe(200);
    const car=await customer.request.post(url+"/vehicles",{data:{label:"Demo Browser Car",transmission:"manual"}});
    expect(car.status()).toBe(201);
    const booking=await customer.request.post(url+"/bookings",{data:{vehicle_id:(await car.json()).id,pickup:"Test pickup in Bengaluru"}});
    expect(booking.status()).toBe(201);
    const id=(await booking.json()).id;
    expect((await driver.request.post(url+"/booking-offers/"+id+"/accept")).status()).toBe(200);
    for(const expected_status of ["ASSIGNED","CONFIRMED","DRIVER_EN_ROUTE"]){
      expect((await driver.request.post(url+"/trips/"+id+"/advance",{data:{expected_status}})).status()).toBe(200);
    }
    expect((await driver.request.post(url+"/handovers/"+id,{data:{stage:"before",odometer:100,fuel_percent:50,condition:"Isolated test handover"}})).status()).toBe(201);
    const page=await customer.newPage();
    await page.goto("/customer/bookings/"+id);
    await expect(page.getByText(/Demo checkout · No money is charged/)).toBeVisible();
    await page.getByRole("button",{name:"Generate pickup code"}).click();
    const code=await page.locator("strong.tracking-widest").innerText();
    expect((await driver.request.post(url+"/trips/"+id+"/pickup-verification/check",{data:{code}})).status()).toBe(200);
    await page.getByRole("button",{name:"Acknowledge",exact:true}).click();
    await expect(page.getByText("acknowledged",{exact:true})).toBeVisible();
    expect((await driver.request.post(url+"/trips/"+id+"/advance",{data:{expected_status:"DRIVER_ARRIVED"}})).status()).toBe(409);
    const checkout=page.getByRole("button",{name:/Simulate payment/});
    expect((await checkout.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(()=>window.document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await checkout.click();
    await expect(page.getByText("simulated",{exact:true})).toBeVisible();
    expect((await driver.request.post(url+"/trips/"+id+"/advance",{data:{expected_status:"DRIVER_ARRIVED"}})).status()).toBe(200);
    await page.goto("/customer/receipts");
    await expect(page.getByText(/No receipts/)).toBeVisible();
  } finally {
    await Promise.all([customer.close(),driver.close(),admin.close()]);
  }
});

test("mobile customer can select a pickup pin and see provider route or fallback",async({page})=>{
  test.skip(process.env.PLAYWRIGHT_MUTATIONS!=="1","Requires a disposable database.");
  await page.setViewportSize({width:360,height:800});
  await page.route("https://tile.openstreetmap.org/**", route=>route.abort());
  await page.request.post("/api/v1/auth/register",{data:{name:"Map Test",email:randomUUID()+"@example.com",password:"long-isolated-map-test-password",role:"customer"}});
  expect((await page.request.post("/api/v1/vehicles",{data:{label:"Map car",transmission:"manual"}})).status()).toBe(201);
  await page.goto("/customer/book");
  await page.getByLabel("Pickup address in Bengaluru").fill("MG Road");
  await page.getByLabel("Destination (optional)").fill("Indiranagar");
  await page.getByText("Set pickup on map or preview route",{exact:true}).click();
  const map=page.getByRole("region",{name:"Interactive pickup map"});
  await expect(map.getByRole("button",{name:"Zoom in"})).toBeVisible();
  await map.click({position:{x:140,y:130}});
  await expect(page.getByText(/^Pickup pin -?\d/)).toBeVisible();
  await page.route("**/api/v1/maps/preview",route=>route.fulfill({
    json:{line:[[12.97,77.59],[12.98,77.64]],distance_m:4700,duration_s:840,provider:"openrouteservice"},
  }),{times:1});
  await page.getByRole("button",{name:"Preview driving route"}).click();
  await expect(page.getByText(/4.7 km · about 14 min/)).toBeVisible();
  await page.getByRole("button",{name:"Preview driving route"}).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(/Routing is unavailable/);
  await expect(page.getByRole("link",{name:"Open route in Google Maps"})).toHaveAttribute("href",/google\.com\/maps\/dir/);
  expect(await page.evaluate(()=>window.document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
});

test("owner signs in to a mobile read-only business dashboard",async({page})=>{
  test.skip(!process.env.PLAYWRIGHT_OWNER_EMAIL || !process.env.PLAYWRIGHT_OWNER_PASSWORD,"Requires disposable owner credentials.");
  await page.setViewportSize({width:360,height:800});
  await page.goto("/owner");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill(process.env.PLAYWRIGHT_OWNER_EMAIL!);
  await page.getByLabel("Password").fill(process.env.PLAYWRIGHT_OWNER_PASSWORD!);
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
  await expect(page).toHaveURL(/\/owner$/);
  await expect(page.getByRole("heading",{name:"Captured revenue"})).toBeVisible();
  await expect(page.getByRole("heading",{name:"Demo checkout activity"})).toBeVisible();
  expect(await page.evaluate(()=>window.document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  expect((await page.request.get("/api/v1/admin/metrics")).status()).toBe(403);
});
