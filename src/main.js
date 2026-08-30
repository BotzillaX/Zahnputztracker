import App from "./App.svelte";
import { mount } from "svelte";
import "./assets/app.css";

export default mount(App, { target: document.getElementById("app") });
