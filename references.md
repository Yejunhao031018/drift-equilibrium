# 参考文献与核实记录
## 《赛车稳态漂移平衡点的非线性优化求解》（非线性优化方法课程论文）

**核实日期**：2026-11-04　**核实人**：团队成员 refs　**条目数**：14 条（4 类各 2–4 篇）+ 1 条可选补充

### 核实方法与判定规则

- **优先一手来源**：Crossref REST API（`api.crossref.org`，按标题/作者检索，并用 `filter=doi:A,doi:B` 批量核对）、`doi.org/api/handles/<DOI>`（判定 DOI 是否真实存在）、出版社/机构官方页面（BnF、JSAE、OSTI、Stanford DDL、Inderscience 期刊目录页）。
- **"查到 DOI"** 一栏：仅在 DOI 经上述途径解析成功时才填"是"；书目存在但无 DOI（部分老书、学位论文、会议论文集）填"否（无 DOI）"。
- **置信度**：高 = 作者/题名/出处/年卷期页均有官方或数据库一手记录；中 = 核心信息（ISBN/作者/题名）有旁证但缺一手页面或存在推定成分；**待核实** = 无法从权威源确证。
- 本文件**不做任何推测性补全**：凡未能确证之处，均在条目 `note` 字段或状态表中显式标注。

---

## 一、数值优化教材与经典算法（4 条）

论文用它来交代"平衡点＝非线性方程组求根/最小二乘解"的算法框架、信赖域与 Levenberg–Marquardt 的实现细节及其收敛性质。

### 1. `nocedal2006numerical`

```bibtex
@book{nocedal2006numerical,
  author    = {Nocedal, Jorge and Wright, Stephen J.},
  title     = {Numerical Optimization},
  edition   = {2},
  series    = {Springer Series in Operations Research and Financial Engineering},
  publisher = {Springer},
  address   = {New York},
  year      = {2006},
  isbn      = {9780387303031},
  doi       = {10.1007/978-0-387-40065-5}
}
```

**本文引用它来支撑**：Newton / 拟 Newton 法求解平衡点方程组 `e(z)=0` 的局部收敛条件，以及以"残差范数 + 步长"为终止准则的工程实现约定。

### 2. `boyd2004convex`

```bibtex
@book{boyd2004convex,
  author    = {Boyd, Stephen and Vandenberghe, Lieven},
  title     = {Convex Optimization},
  publisher = {Cambridge University Press},
  address   = {Cambridge},
  year      = {2004},
  isbn      = {9780521833783},
  doi       = {10.1017/CBO9780511804441}
}
```

**本文引用它来支撑**：说明漂移平衡点问题 `e(z)=0` 本身非凸（刷子轮胎的 `sqrt(max(eps,·))` 摩擦圆约束与三角函数的复合），故只能保证局部解，需要多初值/延拓策略——非凸性判定与"局部最优≠全局最优"的表述依据。

### 3. `more1978levenberg`

```bibtex
@inproceedings{more1978levenberg,
  author    = {Mor{\'e}, Jorge J.},
  title     = {The {Levenberg--Marquardt} Algorithm: Implementation and Theory},
  booktitle = {Numerical Analysis (Proceedings of the Biennial Conference, Dundee 1977)},
  series    = {Lecture Notes in Mathematics},
  volume    = {630},
  publisher = {Springer},
  address   = {Berlin, Heidelberg},
  year      = {1978},
  pages     = {105--116},
  doi       = {10.1007/BFb0067700}
}
```

**本文引用它来支撑**：论文主求解器采用 Levenberg–Marquardt（阻尼最小二乘），此条给出阻尼因子更新规则与"LM 在高斯–牛顿与梯度下降间插值"的理论依据。

> 说明：该卷（LNM 630）编者为 G. A. Watson，但未从一手页面确证，故 `booktitle` 中不写编者字段，避免出错。

### 4. `conn2000trust`

```bibtex
@book{conn2000trust,
  author    = {Conn, Andrew R. and Gould, Nicholas I. M. and Toint, Philippe L.},
  title     = {Trust-Region Methods},
  publisher = {SIAM},
  address   = {Philadelphia, PA},
  year      = {2000},
  isbn      = {9780898714609},
  doi       = {10.1137/1.9780898719857}
}
```

**本文引用它来支撑**：作为"用信赖域而非线搜索"处理强非线性残差的对照文献，用于讨论步长控制与全局化；也用于说明"局部收敛到不稳定平衡点"是算法性质而非模型错误。

---

## 二、车辆动力学与轮胎（4 条）

对应论文的单轨（自行车）模型、准静态载荷转移、摩擦圆与刷子轮胎模型假设。

### 5. `gillespie1992fundamentals`

```bibtex
@book{gillespie1992fundamentals,
  author    = {Gillespie, Thomas D.},
  title     = {Fundamentals of Vehicle Dynamics},
  publisher = {Society of Automotive Engineers (SAE International)},
  address   = {Warrendale, PA},
  year      = {1992},
  isbn      = {9781560911999},
  doi       = {10.4271/R-114}
}
```

**本文引用它来支撑**：纵向/侧向载荷转移的准静态公式与轮胎垂直载荷 `Fz_f, Fz_r` 随加速度变化的写法来源。

### 6. `pacejka2012tire`

```bibtex
@book{pacejka2012tire,
  author    = {Pacejka, Hans B.},
  title     = {Tire and Vehicle Dynamics},
  edition   = {3},
  publisher = {Butterworth-Heinemann},
  address   = {Oxford},
  year      = {2012},
  isbn      = {9780080970165},
  doi       = {10.1016/C2010-0-68548-8},
  note      = {Contributing author: Igo Besselink}
}
```

**本文引用它来支撑**：轮胎侧偏角定义、摩擦圆（combined-slip）约束与"后轮饱和导致稳态漂移"的物理解释；也是刷子/魔术公式类模型的权威总纲。

### 7. `milliken1995race`

```bibtex
@book{milliken1995race,
  author    = {Milliken, William F. and Milliken, Douglas L.},
  title     = {Race Car Vehicle Dynamics},
  publisher = {Society of Automotive Engineers (SAE International)},
  address   = {Warrendale, PA},
  year      = {1995},
  isbn      = {9781560915263}
}
```

**本文引用它来支撑**：赛车场景下"极限工况用侧偏刚度/饱和侧偏力描述"的工程惯例，以及稳态转弯（steady-state cornering）分析的经典处理。

> ⚠ **无 DOI**：`10.4271/R-146` 经 doi.org handle 接口查询返回 `responseCode: 100`（= 该 handle 不存在），Crossref 亦无对应记录，故**不填 DOI**。**置信度：中**——ISBN 978-1-56091-526-3 有书店/馆藏记录印证，年份 1995 与 SAE 出版为通行书目信息，但未能打开出版社一手页面确证（详见状态表）。

### 8. `bernard1995tire`

```bibtex
@inproceedings{bernard1995tire,
  author    = {Bernard, J. E. and Clover, C. L.},
  title     = {Tire Modeling for Low-Speed and High-Speed Calculations},
  booktitle = {SAE Technical Paper Series},
  number    = {950311},
  publisher = {Society of Automotive Engineers},
  address   = {Warrendale, PA},
  year      = {1995},
  doi       = {10.4271/950311}
}
```

**本文引用它来支撑**：刷子轮胎模型（brush model）在低速/高速下的力–滑移解析表达及其数值实现，是论文 `Fy = -M·Φ(u)`、`u = C_α·tan(α)/M` 这一形式的直接模型出处。

> ⚠ **题名更正**：任务书草案写的是 "…low-speed and high-speed **applications**"，实际题名为 "**Calculations**"。另注：SAE 950543 是另一篇（Wakabayashi 等，曲轴扭振），若初稿误引 950543，请改为 950311。

---

## 三、漂移 / 稳态平衡点与分岔分析（4 条）

论文的核心；用于论证"稳态漂移＝开环不稳定的平衡点"这一定性结论。

### 9. `inagaki1994analysis`

```bibtex
@inproceedings{inagaki1994analysis,
  author    = {Inagaki, Shoji and Kushiro, Ikuo and Yamamoto, Masaki},
  title     = {Analysis on Vehicle Stability in Critical Cornering Using Phase-Plane Method},
  booktitle = {Proceedings of the International Symposium on Advanced Vehicle Control (AVEC'94)},
  address   = {Tsukuba, Japan},
  year      = {1994},
  month     = oct,
  pages     = {287--292},
  note      = {JSAE Paper No. 9438411}
}
```

**本文引用它来支撑**：用 β–β̇ 相平面刻画临界（极限）旋回下车辆稳定性与反打方向（countersteer）行为的经典工作，为本文"漂移平衡点位于稳定边界之外"提供实验/相平面旁证。

> ⚠ **重大出处更正**（详见第六节）：任务书草案的题名 "…using bifurcation theory" 与出处 *Int. J. Vehicle Design* **均无法核实**；经 JSAE 官方论文页确证，实际为题名如上、AVEC'94 会议论文集第 287–292 页。另：1995-04 的 *JSAE Review* 16(2):216 载有该文会议摘要，DOI `10.1016/0389-4304(95)94930-L`。

### 10. `ono1998bifurcation`

```bibtex
@article{ono1998bifurcation,
  author  = {Ono, Eiichi and Hosoe, Shigeyuki and Tuan, Hoang D. and Doi, Shun'ichi},
  title   = {Bifurcation in Vehicle Dynamics and Robust Front Wheel Steering Control},
  journal = {IEEE Transactions on Control Systems Technology},
  volume  = {6},
  number  = {3},
  pages   = {412--420},
  year    = {1998},
  month   = may,
  doi     = {10.1109/87.668041}
}
```

**本文引用它来支撑**：把前轮转角作为分岔参数、用分岔理论说明临界车速处平衡点失稳与稳定域边界的工作，为"以平衡点方程 + 雅可比特征值判定漂移解稳定性"的方法论背书。

> ⚠ DOI 为 `10.1109/87.668041`（不是 `…668043`）。

### 11. `hindiyeh2013dynamics`

```bibtex
@phdthesis{hindiyeh2013dynamics,
  author  = {Hindiyeh, Rami},
  title   = {Dynamics and Control of Drifting in Automobiles},
  school  = {Stanford University},
  address = {Stanford, CA},
  year    = {2013},
  month   = mar,
  type    = {{PhD} dissertation},
  url     = {https://ddl.stanford.edu/publications/thesis/dynamics-and-control-drifting-automobiles}
}
```

**本文引用它来支撑**：明确提出"漂移平衡点是开环不稳定平衡点、后轮饱和且横摆主导侧偏动力学"这一定性刻画，以及用"平衡点求解 + 线性化"设计漂移控制器的框架——与本文"先求平衡点再判稳"的路线直接对应。

> ⚠ **无 DOI**（学位论文），以 Stanford Digital Repository 官方页面为准。

### 12. `velenis2010steady`

```bibtex
@article{velenis2010steady,
  author  = {Velenis, Efstathios and Frazzoli, Emilio and Tsiotras, Panagiotis},
  title   = {Steady-State Cornering Equilibria and Stabilisation for a Vehicle during Extreme Operating Conditions},
  journal = {International Journal of Vehicle Autonomous Systems},
  volume  = {8},
  number  = {2/3/4},
  pages   = {217--241},
  year    = {2010},
  doi     = {10.1504/IJVAS.2010.035797}
}
```

**本文引用它来支撑**：用车辆模型直接求解"极限工况下的稳态转弯平衡点"并对之镇定，是本文优化求解稳态漂移平衡点最接近的先行工作（方法对照与结论参照）。

> ⚠ DOI 为 `10.1504/IJVAS.2010.035797`（不是 `…035796`——后者属 Anderson 等的轨迹规划论文）。

---

## 四、稳定性控制（2 条）

用于讨论"平衡点求出来之后如何用线性化/Jacobian 判稳，以及若要做控制器该怎么做"。

### 13. `abe2015vehicle`

```bibtex
@book{abe2015vehicle,
  author    = {Abe, Masato},
  title     = {Vehicle Handling Dynamics: Theory and Application},
  edition   = {2},
  publisher = {Butterworth-Heinemann},
  address   = {Oxford},
  year      = {2015},
  isbn      = {9780081003909},
  doi       = {10.1016/C2014-0-04001-4}
}
```

**本文引用它来支撑**：以线性二自由度模型的特征值/稳定性因数分析车辆稳态与瞬态操纵性的理论框架，对应本文对平衡点雅可比矩阵做特征值分析的解读方式。

> 说明：Crossref 著录该书为 Elsevier, 2015, ISBN 9780081003909（第 1 版 2009 年，ISBN 9781856177498）；"2nd ed." 由两版更替推定，**版次标注置信度为中**，其余字段为高。

### 14. `rajamani2012vehicle`

```bibtex
@book{rajamani2012vehicle,
  author    = {Rajamani, Rajesh},
  title     = {Vehicle Dynamics and Control},
  edition   = {2},
  publisher = {Springer},
  address   = {New York},
  year      = {2012},
  isbn      = {9781461414322},
  doi       = {10.1007/978-1-4614-1433-9}
}
```

**本文引用它来支撑**：ESP/直接横摆力矩控制与 LQR、极点配置在车辆稳定性中的应用，用于论文"结果讨论"部分说明漂移平衡点镇定相对常规稳定性控制的差异。

---

## 五、核实状态总表

| # | 条目 key | 查到 DOI | 置信度 | 来源 URL |
|---|----------|----------|--------|----------|
| 1 | `nocedal2006numerical` | 是（`10.1007/978-0-387-40065-5`） | 高 | https://doi.org/10.1007/978-0-387-40065-5 |
| 2 | `boyd2004convex` | 是（`10.1017/CBO9780511804441`） | 高 | https://doi.org/10.1017/CBO9780511804441 |
| 3 | `more1978levenberg` | 是（`10.1007/BFb0067700`） | 高 | https://doi.org/10.1007/BFb0067700 |
| 4 | `conn2000trust` | 是（`10.1137/1.9780898719857`） | 高 | https://doi.org/10.1137/1.9780898719857 |
| 5 | `gillespie1992fundamentals` | 是（`10.4271/R-114`） | 高 | https://doi.org/10.4271/R-114 |
| 6 | `pacejka2012tire` | 是（`10.1016/C2010-0-68548-8`） | 高 | https://doi.org/10.1016/C2010-0-68548-8 ；版次/ISBN 另见 https://catalogue.bnf.fr/ark:/12148/cb446283069 |
| 7 | `milliken1995race` | **否（无 DOI）** | **中** | https://www.furet.com/livres/race-car-vehicle-dynamics-william-f-milliken-9781560915263.html ；馆藏 https://search.library.wisc.edu/catalog/999773347702121 |
| 8 | `bernard1995tire` | 是（`10.4271/950311`） | 高 | https://doi.org/10.4271/950311 |
| 9 | `inagaki1994analysis` | 否（会议论文，无 DOI；同文会议摘要 DOI `10.1016/0389-4304(95)94930-L`） | 高（题名/出处已更正） | https://tech.jsae.or.jp/paperinfo/en/content/avec1994.46/ |
| 10 | `ono1998bifurcation` | 是（`10.1109/87.668041`） | 高 | https://doi.org/10.1109/87.668041 |
| 11 | `hindiyeh2013dynamics` | 否（学位论文） | 高 | https://ddl.stanford.edu/publications/thesis/dynamics-and-control-drifting-automobiles |
| 12 | `velenis2010steady` | 是（`10.1504/IJVAS.2010.035797`） | 高 | https://doi.org/10.1504/IJVAS.2010.035797 ；卷页见 Inderscience 目录页 |
| 13 | `abe2015vehicle` | 是（`10.1016/C2014-0-04001-4`） | 高（版次标注为中） | https://doi.org/10.1016/C2014-0-04001-4 |
| 14 | `rajamani2012vehicle` | 是（`10.1007/978-1-4614-1433-9`） | 高 | https://doi.org/10.1007/978-1-4614-1433-9 |

**统计**：共 14 条；查到 DOI 11 条；置信度"高"13 条、"中"1 条（`milliken1995race`）；**无需标"待核实"的条目**——草案中的 2 处错误出处（Inagaki、Bernard & Clover）已查实并更正，非"待核实"状态。

---

## 六、与任务书草案的差异与修正（引用时务必按此更正）

| 草案原写法 | 核实后结论 | 处理 |
|-----------|-----------|------|
| Inagaki, Kushiro, Yamamoto (1994) "Analysis of vehicle stability in critical cornering using bifurcation theory", *Int. J. Vehicle Design* | 题名与期刊均不成立。实际为 "Analysis on vehicle stability in critical cornering using **phase-plane method**"，**AVEC'94 会议论文集**（Tsukuba），pp. 287–292 | 已按实文著录（第 9 条）。另核 *IJVD* 1994, 15(3/4/5) 目录（pp. 223–544），全期无 Inagaki 文章，`287–292` 疑为论文集中页码与期刊页码混淆 |
| Bernard & Clover (1995) "Tire modeling for low-speed and high-speed **applications**" | 实为 "…high-speed **Calculations**"，SAE Technical Paper **950311** | 已更正（第 8 条） |
| （若曾按 DOI `10.4271/R-146` 引 Milliken & Milliken） | 该 DOI 不存在（handle 解析 `responseCode: 100`） | 已删除 DOI 字段（第 7 条） |
| （若草案给 Ono 等 DOI `10.1109/87.668043`） | 正确为 `10.1109/87.668041` | 已更正（第 10 条） |
| （若草案给 Velenis 等 DOI `10.1504/IJVAS.2010.035796`） | 正确为 `10.1504/IJVAS.2010.035797`；`…035796` 属 Anderson 等轨迹规划论文 | 已更正（第 12 条） |
| Conn, Gould & Toint 书名 | 官方书名为 *Trust-Region Methods*（Crossref 元数据误作 "Trust Region Methods"） | 按官方书名著录（第 4 条） |
| Moré 的 LM 文献年份（草案写 1980/MINPACK） | LM 算法与实现理论应引 1978 年 LNM 630 章节；MINPACK 软件报告为 1980 年 ANL-80-74 | 主条目改为 1978（第 3 条）；MINPACK 见下方可选补充 |

### 正文写作建议

- 论文正文若需强调"分岔理论"本身（而非车辆应用），建议另补一条**分岔理论方法学**文献（如 Kuznetsov, *Elements of Applied Bifurcation Theory*, Springer）；该条**尚未核实**，如需可交回 refs 再查，切勿直接引用未核实的版本。
- 第 9 条已改为相平面法，若正文论述仍写"用分岔理论研究稳态漂移"，可改引第 10 条（Ono et al. 1998）作为分岔理论出处，第 9 条仅作相平面/实验旁证——两者定位不要混用。

---

## 附：可选补充条目（已核实，未计入上表，按需取用）

若正文明确提到"MINPACK / `lmder` / `hybrd` 等实现"，可补此条：

```bibtex
@techreport{more1980minpack,
  author      = {Mor{\'e}, Jorge J. and Garbow, Burton S. and Hillstrom, Kenneth E.},
  title       = {User Guide for {MINPACK-1}},
  institution = {Argonne National Laboratory},
  address     = {Argonne, IL},
  number      = {ANL-80-74},
  year        = {1980},
  month       = aug,
  doi         = {10.2172/6997568},
  url         = {https://www.osti.gov/biblio/6997568}
}
```

**本文引用它来支撑**：若求解器实际调用 MINPACK 的 LM 实现，则用于交代具体实现来源与参数（`ftol/xtol/gtol`）语义。**置信度：高**（OSTI 记录标题作 "User guide for MINPACK-1. [In FORTRAN]"，报告号 ANL-80-74 一致）。
